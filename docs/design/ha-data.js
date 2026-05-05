// Pulls relevant entities from uploads/lastState.json and exposes a clean shape.
// Loaded synchronously via fetch + a top-level await on a global Promise.

window.HA_READY = (async () => {
  const res = await fetch('lastState.json');
  const data = await res.json();
  const states = data.states;
  const idx = new Map(states.map(s => [s.entity_id, s]));
  const get = (id) => idx.get(id);
  const num = (id) => { const s = get(id); if (!s) return null; const n = parseFloat(s.state); return isNaN(n) ? null : n; };
  const str = (id) => { const s = get(id); return s ? s.state : null; };
  const attr = (id, k) => { const s = get(id); return s ? s.attributes[k] : null; };

  const fetchedAt = new Date(data.fetched_at);

  const w = get(data.weather_entity_id);
  const weather = w ? {
    state: w.state,
    temperature: w.attributes.temperature,
    humidity: w.attributes.humidity,
    windSpeed: w.attributes.wind_speed,
    windBearing: w.attributes.wind_bearing,
    pressure: w.attributes.pressure,
    visibility: w.attributes.visibility,
  } : null;

  const climate = (id) => {
    const s = get(id); if (!s) return null;
    return {
      name: s.attributes.friendly_name,
      mode: s.state,
      current: s.attributes.current_temperature,
      target: s.attributes.temperature,
      action: s.attributes.hvac_action,
    };
  };

  // Pool from water_heater
  const pw = get('water_heater.53_55_raymond_pool');
  const pool = pw ? {
    name: 'Pool',
    operation: pw.state,                       // "Heat Exchanger" or other
    current: pw.attributes.current_temperature,
    target: pw.attributes.temperature,
    air: num('sensor.53_55_raymond_air_sensor'),
    heating: str('binary_sensor.53_55_raymond_heat_exchanger') === 'on',
    pumpRunning: str('binary_sensor.53_55_raymond_filter_pump') === 'on',
    schedule: str('binary_sensor.53_55_raymond_schedule_pool') === 'on',
    freezeProtect: str('binary_sensor.53_55_raymond_freeze') === 'on',
  } : null;

  // Sauna (Saunum Leil)
  const sc = get('climate.saunum_leil');
  const sauna = sc ? {
    mode: sc.state,                            // "off" / "heat" etc
    current: sc.attributes.current_temperature,
    target: sc.attributes.temperature,
    duration: num('number.saunum_leil_sauna_duration'),
    heaters: num('sensor.saunum_leil_heater_elements_active'),
    door: str('binary_sensor.saunum_leil_door') === 'on',
    light: str('light.saunum_leil_light') === 'on',
    roomTemp: num('sensor.usl_environmental_temperature_2'),
    roomHumidity: num('sensor.usl_environmental_humidity_2'),
  } : null;

  // Washer
  const washerStatus = str('sensor.washer_current_status');     // "power_off" etc
  const washerOp = str('select.washer_operation');
  const washerRemaining = str('sensor.washer_remaining_time');
  const washerLastNotif = get('event.washer_notification');
  const washer = {
    status: washerStatus,
    operation: washerOp,
    remaining: washerRemaining,
    lastNotification: washerLastNotif ? {
      type: washerLastNotif.attributes.event_type,
      at: washerLastNotif.state,
    } : null,
    powerOn: str('switch.washer_power') === 'on',
    cycles: num('sensor.washer_cycles'),
    energyMonth: num('sensor.washer_energy_this_month'),
  };

  // Dishwasher
  const dwState = str('sensor.dishwasher_operation_state');
  const dishwasher = {
    state: dwState,
    program: str('select.dishwasher_selected_program'),
    progress: num('sensor.dishwasher_program_progress'),
    finishTime: str('sensor.dishwasher_program_finish_time'),
    door: str('sensor.dishwasher_door'),
    powerOn: str('switch.dishwasher_power') === 'on',
    connected: str('binary_sensor.dishwasher_connectivity') === 'on',
  };

  // House climate — top-level zones
  const climates = {
    basement: climate('climate.basement'),
    first: climate('climate.first_floor'),
    second: climate('climate.second_floor'),
    third: climate('climate.third_floor'),
    radiantMain: climate('climate.nest_learning_thermostat_4th_gen'),
    radiantApt: climate('climate.nest_learning_thermostat_4th_gen_3'),
  };

  // ALL climate entities — for accurate active-counts
  const allClimates = states.filter(s =>
    s.entity_id.startsWith('climate.') &&
    s.state !== 'unavailable' &&
    s.entity_id !== 'climate.saunum_leil' &&
    !s.entity_id.includes('serial_test')
  ).map(s => ({
    id: s.entity_id,
    name: s.attributes.friendly_name,
    mode: s.state,
    current: s.attributes.current_temperature,
    target: s.attributes.temperature,
    action: s.attributes.hvac_action,
  }));

  // Group by floor (best-effort heuristic on entity name)
  const floorOf = (id) => {
    if (/^climate\.(1st|first)/.test(id)) return 'first';
    if (/^climate\.(2nd|second)/.test(id)) return 'second';
    if (/^climate\.(3rd|third)/.test(id)) return 'third';
    if (/^climate\.(bsmt|basement)/.test(id)) return 'basement';
    if (/above_garage|tree_house|workshop|gym|master_bedroom/.test(id)) return 'other';
    return null;
  };
  const floorActivity = { first:[], second:[], third:[], basement:[], other:[] };
  allClimates.forEach(c => {
    const f = floorOf(c.id); if (!f) return;
    floorActivity[f].push(c);
  });
  const floorHeatCount = (f) => floorActivity[f].filter(c => c.action === 'heating').length;
  const floorAnyHeating = (f) => floorActivity[f].some(c => c.action === 'heating');

  const temps = {
    basement: num('sensor.basement_temperature'),
    first: num('sensor.first_floor_temperature'),
    second: num('sensor.second_floor_temperature'),
    third: num('sensor.third_floor_temperature'),
    outdoor: num('sensor.weather_station_outdoor_temperature'),
  };

  // People
  const people = states.filter(s => s.entity_id.startsWith('person.')).map(s => ({
    name: s.attributes.friendly_name,
    state: s.state,
  }));

  // Garage
  const garage = {
    state: str('cover.smart_garage_door_25090565132271610701c4e7ae20a653_garage'),
  };

  // Open windows: covers that are not shades/skylights/garage and state == open
  const openWindows = states.filter(s =>
    s.entity_id.startsWith('cover.') &&
    !/shade|blind|curtain|skylight|garage/i.test(s.entity_id + ' ' + (s.attributes.friendly_name||'')) &&
    s.state === 'open'
  ).map(s => ({ id: s.entity_id, name: s.attributes.friendly_name }));

  // Sun
  const sun = {
    state: str('sun.sun'),
    nextDawn: str('sensor.sun_next_dawn'),
    nextDusk: str('sensor.sun_next_dusk'),
    nextSetting: str('sensor.sun_next_setting'),
    nextRising: str('sensor.sun_next_rising'),
  };

  return {
    fetchedAt,
    weather, climates, temps, people, garage, openWindows, sun,
    pool, sauna, washer, dishwasher,
    allClimates, floorActivity, floorHeatCount, floorAnyHeating,
  };
})();
