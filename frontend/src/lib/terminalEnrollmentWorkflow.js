import {
  cancelTerminalEnrollmentIntent,
  completeTerminalEnrollmentIntent,
  createTerminalEnrollmentIntent,
  getTerminalEnrollmentIntent,
  issueTerminalEnrollmentTicket,
} from './terminalEnrollmentApi.js';
import {
  Ret1ProtocolError,
  buildEnrollmentConfig,
  clearMutableBytes,
  completeHandshake,
  decryptResult,
  encodeBase64Url,
  encodeRet1Frame,
  encryptProvision,
  generateClientHello,
  sha256,
  validateEnrollmentWifi,
  validateHelloAck,
  validateStatus,
} from './terminalEnrollmentProtocol.js';
import {
  TerminalEnrollmentTransportError,
  readTerminalEnrollmentResponse,
} from './terminalEnrollmentTransport.js';
import { runTerminalFirmwareInstallPhase } from './terminalFirmwareInstallWorkflow.js';

const BAUD_RATE = 115200;
const SHA256_PATTERN = /^[0-9a-f]{64}$/u;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const MAC_PATTERN = /^[0-9a-f]{2}(?::[0-9a-f]{2}){5}$/u;
const IDENTIFIER_PATTERN = /^[A-Za-z0-9._-]{1,64}$/u;
const TERMINAL_STATES = new Set([
  'initialized', 'issued', 'client_confirmed', 'activated', 'expired', 'superseded', 'review',
]);
const textEncoder = new TextEncoder();

const DEFAULT_API = Object.freeze({
  cancelIntent: cancelTerminalEnrollmentIntent,
  createIntent: createTerminalEnrollmentIntent,
  issueTicket: issueTerminalEnrollmentTicket,
  completeIntent: completeTerminalEnrollmentIntent,
  getIntent: getTerminalEnrollmentIntent,
});

const DEFAULT_PROTOCOL = Object.freeze({
  buildEnrollmentConfig,
  clearMutableBytes,
  completeHandshake,
  decryptResult,
  encodeBase64Url,
  encodeRet1Frame,
  encryptProvision,
  generateClientHello,
  sha256,
  validateEnrollmentWifi,
  validateHelloAck,
  validateStatus,
});

export const TERMINAL_ENROLLMENT_WORKFLOW_STATES = Object.freeze([
  'preflight',
  'sending_hello',
  'verifying_identity',
  'creating_intent',
  'preparing_configuration',
  'issuing_ticket',
  'writing_configuration',
  'verifying_result',
  'reporting_result',
  'activation_pending',
  'activated',
  'cancelled_before_write',
  'blocked',
  'result_unknown',
  'activation_delayed',
]);

const PRESENTATIONS = Object.freeze({
  preflight: ['neutral', 'Enrollment preflight', 'Checking exact firmware, server policy, and local network input.'],
  sending_hello: ['neutral', 'Opening secure session', 'Sending one ephemeral RET1 hello over the retained terminal port.'],
  verifying_identity: ['neutral', 'Verifying observed identity', 'Binding model, release, MAC, generation, and physical-cable transcript.'],
  creating_intent: ['neutral', 'Authorizing terminal', 'The application is accepting only the public RET1 transcript.'],
  preparing_configuration: ['neutral', 'Preparing local configuration', 'Wi-Fi values and the raw device credential stay in this browser-to-terminal session.'],
  issuing_ticket: ['neutral', 'Issuing one-time ticket', 'Only credential and configuration hashes are sent to the application.'],
  writing_configuration: ['warning', 'Writing encrypted configuration', 'Do not unplug the terminal. The outcome becomes uncertain if this frame is interrupted.'],
  verifying_result: ['warning', 'Verifying terminal commit', 'Waiting for the authenticated generation and configuration-hash result.'],
  reporting_result: ['warning', 'Recording browser result', 'The terminal committed and is rebooting; browser confirmation does not activate it.'],
  activation_pending: ['warning', 'Waiting for secure check-in', 'Only the terminal’s first credential-authenticated HTTPS check-in can activate enrollment.'],
  activated: ['success', 'Terminal securely enrolled', 'The server observed the exact candidate credential and terminal identity.'],
  cancelled_before_write: ['neutral', 'Enrollment cancelled safely', 'No encrypted configuration frame began writing to the terminal.'],
  blocked: ['danger', 'Enrollment blocked', 'Identity, policy, ticket, or local validation failed before terminal configuration changed.'],
  result_unknown: ['danger', 'Configuration result unknown', 'Do not retry automatically. Keep the cable attached and reconcile the durable generation first.'],
  activation_delayed: ['warning', 'Configuration committed; check-in delayed', 'The terminal confirmed its new generation, but Wi-Fi or HTTPS activation has not reached the server.'],
});

export class TerminalEnrollmentWorkflowError extends Error {
  constructor(code, message) {
    super(message);
    this.name = 'TerminalEnrollmentWorkflowError';
    this.code = code;
  }
}

function fail(code, message) {
  throw new TerminalEnrollmentWorkflowError(code, message);
}

function abortError() {
  const error = new Error('Terminal enrollment was cancelled.');
  error.name = 'AbortError';
  return error;
}

function throwIfAborted(signal) {
  if (signal?.aborted) throw abortError();
}

function cryptoRuntime(runtime) {
  const value = runtime?.crypto || runtime;
  if (typeof value?.getRandomValues !== 'function' || typeof value?.subtle?.digest !== 'function') {
    fail('crypto_unavailable', 'Browser cryptography is unavailable.');
  }
  return value;
}

function randomUuid(runtime) {
  const value = runtime.getRandomValues(new Uint8Array(16));
  value[6] = (value[6] & 0x0f) | 0x40;
  value[8] = (value[8] & 0x3f) | 0x80;
  const encoded = [...value].map(item => item.toString(16).padStart(2, '0')).join('');
  clearMutableBytes(value);
  return `${encoded.slice(0, 8)}-${encoded.slice(8, 12)}-${encoded.slice(12, 16)}-${encoded.slice(16, 20)}-${encoded.slice(20)}`;
}

function hex(value) {
  return [...value].map(item => item.toString(16).padStart(2, '0')).join('');
}

function exactObject(value, keys, code, label) {
  if (value === null
    || typeof value !== 'object'
    || Array.isArray(value)
    || Object.keys(value).length !== keys.length
    || !keys.every(key => Object.hasOwn(value, key))) {
    fail(code, `${label} has an unexpected response shape.`);
  }
  return value;
}

function expectedContract(value) {
  if (!value
    || !SHA256_PATTERN.test(value.releaseId)
    || !IDENTIFIER_PATTERN.test(value.enrollmentKeyId)
    || !['E1001', 'E1002'].includes(value.model)
    || typeof value.firmwareVersion !== 'string'
    || value.firmwareVersion.length < 1
    || value.firmwareVersion.length > 128
    || !MAC_PATTERN.test(value.factoryMac)) {
    fail('preflight_invalid', 'Expected RET1 enrollment identity is incomplete.');
  }
  return Object.freeze({ ...value });
}

function validatedStatus(value, expected, protocol) {
  let status;
  try {
    status = protocol.validateStatus(value);
  } catch (error) {
    if (error instanceof Ret1ProtocolError) fail('status_invalid', 'Post-flash RET1 status is malformed.');
    throw error;
  }
  if (status.v !== 2
    || status.state === 'storage_error'
    || status.enrollment_available !== true
    || status.enrollment_key_id !== expected.enrollmentKeyId
    || status.model !== expected.model
    || status.firmware_version !== expected.firmwareVersion
    || status.factory_mac !== expected.factoryMac
    || status.partition_layout !== 'ab-v1'
    || status.running_partition !== 'ota_0'
    || status.partition_identity_valid !== true
    || status.boot_state !== 'stable') {
    fail('status_mismatch', 'Post-flash terminal is not eligible for exact RET1 enrollment.');
  }
  return status;
}

function validateAckAgainstStatus(value, status, protocol) {
  let acknowledgement;
  try {
    acknowledgement = protocol.validateHelloAck(value).message;
  } catch (error) {
    if (error instanceof Ret1ProtocolError) fail('hello_ack_invalid', 'RET1 hello acknowledgement is malformed.');
    throw error;
  }
  if (acknowledgement.model !== status.model
    || acknowledgement.firmware_version !== status.firmware_version
    || acknowledgement.factory_mac !== status.factory_mac
    || acknowledgement.config_generation !== status.config_generation) {
    fail('identity_mismatch', 'RET1 hello identity differs from the verified post-flash status.');
  }
  return acknowledgement;
}

function validateAttemptRecord(record, expected, handshake, attemptId = null) {
  exactObject(record, [
    'schema_version', 'attempt_id', 'state', 'operation', 'session_id', 'terminal',
    'firmware_release', 'schedule_url_template', 'expires_at', 'client_completed_at', 'activated_at',
  ], 'server_response_invalid', 'Enrollment intent');
  exactObject(record.terminal, [
    'id', 'model', 'factory_mac', 'firmware_version', 'observed_generation', 'target_generation',
  ], 'server_response_invalid', 'Enrollment terminal');
  exactObject(record.firmware_release, ['release_id', 'enrollment_key_id'], 'server_response_invalid', 'Enrollment release');
  if (record.schema_version !== 1
    || !UUID_PATTERN.test(record.attempt_id)
    || (attemptId && record.attempt_id.toLowerCase() !== attemptId.toLowerCase())
    || !TERMINAL_STATES.has(record.state)
    || record.operation !== 'provision'
    || record.session_id !== handshake.sessionId
    || !UUID_PATTERN.test(record.terminal.id)
    || record.terminal.model !== expected.model
    || record.terminal.factory_mac !== expected.factoryMac
    || record.terminal.firmware_version !== expected.firmwareVersion
    || record.terminal.observed_generation !== handshake.configGeneration
    || record.terminal.target_generation !== handshake.configGeneration + 1
    || record.firmware_release.release_id !== expected.releaseId
    || record.firmware_release.enrollment_key_id !== expected.enrollmentKeyId
    || typeof record.schedule_url_template !== 'string') {
    fail('server_response_mismatch', 'Enrollment intent does not match the observed terminal session.');
  }
  return record;
}

function validateTicketRecord(record, attemptId, targetGeneration, configSha256) {
  exactObject(record, [
    'schema_version', 'attempt_id', 'state', 'operation', 'generation', 'config_sha256',
    'ticket', 'issued_at', 'expires_at', 'activation',
  ], 'server_response_invalid', 'Enrollment ticket');
  if (record.schema_version !== 1
    || record.attempt_id.toLowerCase() !== attemptId.toLowerCase()
    || !['issued', 'client_confirmed', 'activated'].includes(record.state)
    || record.operation !== 'provision'
    || record.generation !== targetGeneration
    || record.config_sha256 !== configSha256
    || typeof record.ticket !== 'string'
    || record.ticket.length < 64
    || record.ticket.length > 4096
    || record.activation !== 'first_scoped_https_checkin') {
    fail('server_response_mismatch', 'Enrollment ticket does not match the exact configuration transition.');
  }
  return record;
}

function scheduleUrl(template, credential) {
  if (typeof template !== 'string'
    || template.length > 1400
    || template.split('{credential}').length !== 2
    || template.replace('{credential}', '').includes('{')
    || template.replace('{credential}', '').includes('}')) {
    fail('schedule_template_invalid', 'Enrollment schedule URL template is invalid.');
  }
  return template.replace('{credential}', credential);
}

function apiContract(api, methods) {
  for (const method of methods) {
    if (typeof api?.[method] !== 'function') fail('api_invalid', `Enrollment API is missing ${method}().`);
  }
  return api;
}

function transportContract(transport) {
  for (const method of ['sendRet1Frame', 'readChunks']) {
    if (typeof transport?.[method] !== 'function') fail('transport_invalid', `RET1 transport is missing ${method}().`);
  }
  return transport;
}

function frozenEvent(state, detail = {}) {
  return Object.freeze({ state, ...detail });
}

function notify(callback, event) {
  try {
    callback(event);
  } catch {
    // UI observers cannot interrupt or change the enrollment transaction.
  }
}

function delay(milliseconds, signal) {
  throwIfAborted(signal);
  return new Promise((resolve, reject) => {
    const timer = setTimeout(finish(resolve), milliseconds);
    const onAbort = () => finish(reject)(abortError());
    function finish(callback) {
      return value => {
        clearTimeout(timer);
        signal?.removeEventListener?.('abort', onAbort);
        callback(value);
      };
    }
    signal?.addEventListener?.('abort', onAbort, { once: true });
  });
}

function normalizeError(error) {
  if (error instanceof TerminalEnrollmentWorkflowError) return error;
  if (error instanceof TerminalEnrollmentTransportError || error instanceof Ret1ProtocolError) {
    return new TerminalEnrollmentWorkflowError(error.code || 'protocol_failed', error.message);
  }
  if (error?.name === 'AbortError') {
    return new TerminalEnrollmentWorkflowError('cancelled', 'Terminal enrollment was cancelled.');
  }
  return new TerminalEnrollmentWorkflowError(
    typeof error?.code === 'string' ? error.code : 'enrollment_failed',
    error?.message || 'Terminal enrollment failed closed.',
  );
}

async function safeClose(...transports) {
  await Promise.allSettled([...new Set(transports.filter(Boolean))].map(transport => transport.close?.()));
}

export function describeTerminalEnrollmentState(state, errorCode = '') {
  const [tone, title, detail] = PRESENTATIONS[state] || PRESENTATIONS.blocked;
  return Object.freeze({
    state: Object.hasOwn(PRESENTATIONS, state) ? state : 'blocked',
    tone,
    title,
    detail,
    errorCode: typeof errorCode === 'string' ? errorCode : '',
    irreversible: ['writing_configuration', 'verifying_result', 'reporting_result', 'result_unknown'].includes(state),
    activated: state === 'activated',
  });
}

export async function runTerminalEnrollmentPhase({
  status: inputStatus,
  expected: inputExpected,
  credentials,
  applicationTransport,
  api = DEFAULT_API,
  protocol = DEFAULT_PROTOCOL,
  runtime = globalThis.crypto,
  signal,
  onState = () => {},
  responseTimeoutMs = 12_000,
}) {
  const history = [];
  let state = 'preflight';
  let provisionMayHaveStarted = false;
  let deviceCommitted = false;
  let attemptId = null;
  let clientIntentId = null;
  let terminalId = null;
  let targetGeneration = null;
  let configBytes = null;
  let configDigest = null;
  let credentialDigest = null;
  let expected = null;
  let handshake = null;
  const emit = (next, detail = {}) => {
    state = next;
    const event = frozenEvent(next, detail);
    history.push(event);
    notify(onState, event);
  };
  const finish = (ok, next, error = null) => Object.freeze({
    ok,
    state: next,
    error,
    attemptId,
    terminalId,
    targetGeneration,
    deviceCommitted,
    activationPending: next === 'activation_pending',
    history: Object.freeze([...history]),
  });

  emit('preflight');
  try {
    throwIfAborted(signal);
    const crypto = cryptoRuntime(runtime);
    expected = expectedContract(inputExpected);
    const client = apiContract(api, [
      'cancelIntent', 'createIntent', 'issueTicket', 'completeIntent', 'getIntent',
    ]);
    const transport = transportContract(applicationTransport);
    protocol.validateEnrollmentWifi(credentials);
    const status = validatedStatus(inputStatus, expected, protocol);

    emit('sending_hello');
    const generated = await protocol.generateClientHello(crypto);
    await transport.sendRet1Frame({
      baudRate: BAUD_RATE,
      bytes: protocol.encodeRet1Frame(generated.hello),
      signal,
    });
    const helloAck = await readTerminalEnrollmentResponse({
      chunks: transport.readChunks({ baudRate: BAUD_RATE, signal }),
      expectedType: 'hello_ack',
      signal,
      timeoutMs: responseTimeoutMs,
    });

    emit('verifying_identity');
    validateAckAgainstStatus(helloAck, status, protocol);
    handshake = await protocol.completeHandshake({
      hello: generated.hello,
      helloAck,
      clientPrivateKey: generated.clientPrivateKey,
      runtime: crypto,
    });
    if (handshake.model !== expected.model
      || handshake.firmwareVersion !== expected.firmwareVersion
      || handshake.factoryMac !== expected.factoryMac
      || handshake.configGeneration !== status.config_generation) {
      fail('identity_mismatch', 'Derived RET1 session does not match the verified terminal.');
    }

    emit('creating_intent');
    clientIntentId = randomUuid(crypto);
    const intent = validateAttemptRecord(await client.createIntent({
      client_intent_id: clientIntentId,
      operation: 'provision',
      status,
      hello: generated.hello,
      hello_ack: helloAck,
    }), expected, handshake);
    attemptId = intent.attempt_id;
    terminalId = intent.terminal.id;
    targetGeneration = intent.terminal.target_generation;

    emit('preparing_configuration');
    const credentialBytes = crypto.getRandomValues(new Uint8Array(32));
    const credential = protocol.encodeBase64Url(credentialBytes);
    protocol.clearMutableBytes(credentialBytes);
    if (credential.length !== 43) fail('credential_invalid', 'Generated terminal credential is invalid.');
    const credentialText = textEncoder.encode(credential);
    try {
      credentialDigest = await protocol.sha256(credentialText, crypto);
    } finally {
      protocol.clearMutableBytes(credentialText);
    }
    const built = protocol.buildEnrollmentConfig({
      ssid: credentials.ssid,
      password: credentials.password,
      scheduleUrl: scheduleUrl(intent.schedule_url_template, credential),
    });
    configBytes = built.bytes;
    configDigest = await protocol.sha256(configBytes, crypto);
    const credentialSha256 = hex(credentialDigest);
    const configSha256 = hex(configDigest);

    emit('issuing_ticket');
    const clientTicketId = randomUuid(crypto);
    const ticket = validateTicketRecord(await client.issueTicket(attemptId, {
      client_ticket_id: clientTicketId,
      credential_sha256: credentialSha256,
      config_sha256: configSha256,
    }), attemptId, targetGeneration, configSha256);
    throwIfAborted(signal);

    const provision = await protocol.encryptProvision({
      handshake,
      ticket: ticket.ticket,
      configBytes,
      expectedKeyId: expected.enrollmentKeyId,
      runtime: crypto,
    });
    if (hex(provision.configSha256) !== configSha256) {
      fail('config_hash_mismatch', 'Encrypted configuration hash changed before the terminal write.');
    }
    protocol.clearMutableBytes(configBytes);
    configBytes = null;

    emit('writing_configuration');
    provisionMayHaveStarted = true;
    await transport.sendRet1Frame({ baudRate: BAUD_RATE, bytes: provision.frame, signal });
    emit('verifying_result');
    const resultEnvelope = await readTerminalEnrollmentResponse({
      chunks: transport.readChunks({ baudRate: BAUD_RATE, signal }),
      expectedType: 'result',
      expectedSessionId: handshake.sessionId,
      signal,
      timeoutMs: responseTimeoutMs,
    });
    const result = await protocol.decryptResult({
      handshake,
      ticket: ticket.ticket,
      message: resultEnvelope,
      expected: {
        operation: 'provision',
        generation: targetGeneration,
        configSha256: configDigest,
      },
      runtime: crypto,
    });
    if (!result.ok || result.generation !== targetGeneration) {
      fail('result_mismatch', 'Terminal result does not match the authorized configuration generation.');
    }
    deviceCommitted = true;

    emit('reporting_result');
    const completed = validateAttemptRecord(await client.completeIntent(attemptId, {
      client_ticket_id: clientTicketId,
      operation: 'provision',
      generation: targetGeneration,
      config_sha256: configSha256,
    }), expected, handshake, attemptId);
    if (completed.state === 'activated') {
      emit('activated', { terminalId, generation: targetGeneration });
      return finish(true, 'activated');
    }
    if (completed.state !== 'client_confirmed') {
      fail('server_response_mismatch', 'Server did not retain the committed enrollment result.');
    }
    emit('activation_pending', { terminalId, generation: targetGeneration });
    return finish(true, 'activation_pending');
  } catch (rawError) {
    let error = normalizeError(rawError);
    if (deviceCommitted) {
      emit('activation_pending', { code: error.code });
      return finish(true, 'activation_pending', error);
    }
    if (provisionMayHaveStarted) {
      emit('result_unknown', { code: error.code });
      return finish(false, 'result_unknown', error);
    }
    let cancellationConfirmed = attemptId === null;
    if (attemptId && clientIntentId && expected && handshake) {
      try {
        const cancelled = validateAttemptRecord(await api.cancelIntent(attemptId, {
          client_intent_id: clientIntentId,
          operation: 'cancel',
        }), expected, handshake, attemptId);
        cancellationConfirmed = cancelled.state === 'superseded';
        if (!cancellationConfirmed) {
          throw new TerminalEnrollmentWorkflowError(
            'cancellation_failed',
            'The enrollment attempt was not safely superseded.',
          );
        }
      } catch {
        cancellationConfirmed = false;
        error = new TerminalEnrollmentWorkflowError(
          'cancellation_failed',
          'The pre-write enrollment attempt could not be safely superseded. Reconcile it before retrying.',
        );
      }
    }
    const next = rawError?.name === 'AbortError' && cancellationConfirmed
      ? 'cancelled_before_write'
      : 'blocked';
    emit(next, { code: error.code });
    return finish(false, next, error);
  } finally {
    if (configBytes) protocol.clearMutableBytes(configBytes);
    if (configDigest) protocol.clearMutableBytes(configDigest);
    if (credentialDigest) protocol.clearMutableBytes(credentialDigest);
  }
}

export async function waitForTerminalEnrollmentActivation({
  attemptId,
  api = DEFAULT_API,
  signal,
  timeoutMs = 45_000,
  pollMs = 1500,
}) {
  if (!UUID_PATTERN.test(attemptId)
    || !Number.isSafeInteger(timeoutMs)
    || timeoutMs < 0
    || timeoutMs > 120_000
    || !Number.isSafeInteger(pollMs)
    || pollMs < 1
    || pollMs > 10_000) {
    fail('activation_poll_invalid', 'Enrollment activation poll contract is invalid.');
  }
  const client = apiContract(api, ['getIntent']);
  const expiresAt = Date.now() + timeoutMs;
  while (true) {
    throwIfAborted(signal);
    const record = await client.getIntent(attemptId);
    if (!record || record.attempt_id?.toLowerCase() !== attemptId.toLowerCase() || !TERMINAL_STATES.has(record.state)) {
      fail('server_response_invalid', 'Enrollment activation response is invalid.');
    }
    if (record.state === 'activated') return Object.freeze({ activated: true, record });
    if (['expired', 'superseded', 'review'].includes(record.state)) {
      return Object.freeze({ activated: false, terminal: true, record });
    }
    const remaining = expiresAt - Date.now();
    if (remaining <= 0) return Object.freeze({ activated: false, terminal: false, record });
    await delay(Math.min(pollMs, remaining), signal);
  }
}

export async function runTerminalFirmwareProvisioningWorkflow({
  preparedPlan,
  expectedEnrollment,
  credentials,
  romTransport,
  applicationTransport,
  api = DEFAULT_API,
  protocol = DEFAULT_PROTOCOL,
  runtime = globalThis.crypto,
  signal,
  onFirmwareState = () => {},
  onEnrollmentState = () => {},
  onProgress = () => {},
  statusTimeoutMs = 5000,
  statusSettleMs = 850,
  responseTimeoutMs = 12_000,
  activationTimeoutMs = 45_000,
  activationPollMs = 1500,
}) {
  let firmwareResult = null;
  let enrollmentResult = null;
  try {
    firmwareResult = await runTerminalFirmwareInstallPhase({
      preparedPlan,
      romTransport,
      applicationTransport,
      signal,
      onState: onFirmwareState,
      onProgress,
      statusTimeoutMs,
      statusSettleMs,
    });
    if (!firmwareResult.ok) {
      return Object.freeze({ ok: false, state: firmwareResult.state, firmware: firmwareResult, enrollment: null });
    }
    enrollmentResult = await runTerminalEnrollmentPhase({
      status: firmwareResult.status,
      expected: {
        ...expectedEnrollment,
        factoryMac: firmwareResult.probe.factoryMac,
      },
      credentials,
      applicationTransport,
      api,
      protocol,
      runtime,
      signal,
      onState: onEnrollmentState,
      responseTimeoutMs,
    });
  } finally {
    await safeClose(applicationTransport, romTransport);
  }

  if (!enrollmentResult?.attemptId
    || !['activation_pending', 'result_unknown'].includes(enrollmentResult.state)) {
    return Object.freeze({
      ok: Boolean(firmwareResult?.ok && enrollmentResult?.state === 'activated'),
      state: enrollmentResult?.state || firmwareResult?.state || 'blocked',
      firmware: firmwareResult,
      enrollment: enrollmentResult,
    });
  }

  try {
    const activation = await waitForTerminalEnrollmentActivation({
      attemptId: enrollmentResult.attemptId,
      api,
      signal,
      timeoutMs: activationTimeoutMs,
      pollMs: activationPollMs,
    });
    if (activation.activated) {
      const event = frozenEvent('activated', {
        terminalId: enrollmentResult.terminalId,
        generation: enrollmentResult.targetGeneration,
      });
      notify(onEnrollmentState, event);
      return Object.freeze({
        ok: true,
        state: 'activated',
        firmware: firmwareResult,
        enrollment: Object.freeze({ ...enrollmentResult, ok: true, state: 'activated' }),
      });
    }
    const state = enrollmentResult.state === 'result_unknown' ? 'result_unknown' : 'activation_delayed';
    notify(onEnrollmentState, frozenEvent(state, {
      terminalId: enrollmentResult.terminalId,
      generation: enrollmentResult.targetGeneration,
    }));
    return Object.freeze({
      ok: false,
      state,
      firmware: firmwareResult,
      enrollment: Object.freeze({ ...enrollmentResult, state }),
    });
  } catch (rawError) {
    const state = enrollmentResult.state === 'result_unknown' ? 'result_unknown' : 'activation_delayed';
    notify(onEnrollmentState, frozenEvent(state, { code: normalizeError(rawError).code }));
    return Object.freeze({
      ok: false,
      state,
      firmware: firmwareResult,
      enrollment: Object.freeze({ ...enrollmentResult, state, error: normalizeError(rawError) }),
    });
  }
}
