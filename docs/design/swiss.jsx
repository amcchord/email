// SWISS / MODULAR — 800x480
// Müller-Brockmann meets Wim Crouwel: dramatic scale contrast, thick/thin rules,
// pixel fonts for data readouts, restrained but committed use of color.

// E-ink palettes: no greys (the panels can't render them).
// Differentiation comes from weight, scale, and dotted/hairline rules — not value.
const SW_PALETTE = {
  six: {
    bg:    '#ffffff',
    ink:   '#0a0a0a',
    paper: '#ffffff',
    red:   '#c8261b',
    blue:  '#1d4d8a',
    green: '#1f6b3a',
    yellow:'#e7b800',
    rule:  '#0a0a0a',
    soft:  '#0a0a0a',  // used only as a thin rule background
    muted: '#0a0a0a',  // ink — no grey
  },
  bw: {
    bg:'#ffffff', ink:'#000000', paper:'#ffffff',
    red:'#000000', blue:'#000000', green:'#000000', yellow:'#000000',
    rule:'#000000', soft:'#000000', muted:'#000000',
  },
};

// ---- typography ----
// Sans for big display digits + Cherry/Tamzen pixel fonts for ISO data
const SW_TY = {
  display: { fontFamily: '"Helvetica Neue", "Inter", "Arial", sans-serif', fontWeight: 700, letterSpacing: '-0.045em' },
  sans:    { fontFamily: '"Helvetica Neue", "Inter", "Arial", sans-serif', fontWeight: 500 },
  cherry:  { fontFamily: '"Cherry", monospace', fontWeight: 400 },
  cherryB: { fontFamily: '"Cherry", monospace', fontWeight: 700 },
  cherrySm:{ fontFamily: '"Cherry Small", monospace', fontWeight: 400 },
  cherrySmB:{fontFamily: '"Cherry Small", monospace', fontWeight: 700 },
  tamzen:  { fontFamily: '"Tamzen", monospace', fontWeight: 400 },
  tamzenB: { fontFamily: '"Tamzen", monospace', fontWeight: 700 },
};

function SwissDashboard({ ha, palette }) {
  const P = palette;
  const now = ha.fetchedAt;
  const active = window.pickActive(ha);
  const hasActive = active.length > 0;
  const lead = active[0];

  // Hairline rule helper
  const HL = `0.75px solid ${P.rule}`;
  const TH = `2px solid ${P.rule}`;

  return (
    <div style={{
      width: 800, height: 480, background: P.bg, color: P.ink,
      boxSizing: 'border-box', position: 'relative', overflow: 'hidden',
      ...SW_TY.sans,
    }}>
      {/* === MASTHEAD: thick top rule, dossier-style metadata === */}
      <div style={{
        height: 36, borderBottom: TH,
        display: 'grid', gridTemplateColumns: '180px 1fr 200px 110px',
        alignItems: 'stretch',
      }}>
        <div style={{ padding: '0 14px', display: 'flex', alignItems: 'center', borderRight: HL,
                      background: P.ink, color: P.bg }}>
          <span style={{ ...SW_TY.cherryB, fontSize: 13, letterSpacing: '0.20em' }}>CAMBRIDGE</span>
        </div>
        <div style={{ padding: '0 14px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderRight: HL }}>
          <span style={{ ...SW_TY.cherrySmB, fontSize: 11, letterSpacing: '0.14em', color: P.ink }}>
            HOME STATUS
          </span>
          <span style={{ ...SW_TY.cherrySm, fontSize: 11, letterSpacing: '0.14em', color: P.ink }}>
            {window.fmtDate(now).toUpperCase()}
          </span>
        </div>
        <div style={{ padding: '0 14px', display: 'flex', alignItems: 'center', borderRight: HL }}>
          <span style={{ ...SW_TY.cherrySmB, fontSize: 11, letterSpacing: '0.14em' }}>
            {hasActive ? <span style={{ color: P.red }}>● {active.length} ACTIVE</span> : <span style={{ color: P.muted }}>○ NOMINAL</span>}
          </span>
        </div>
        <div style={{ padding: '0 14px', display: 'flex', alignItems: 'center', justifyContent: 'flex-end' }}>
          <span style={{ ...SW_TY.cherrySmB, fontSize: 11, letterSpacing: '0.14em', color: P.muted }}>
            ↻ {window.fmtTime(now).toUpperCase().replace(' ','')}
          </span>
        </div>
      </div>

      {/* === MAIN GRID ===
          Two-column body. Left: hero/active.  Right: instruments stack.
          The grid is intentionally asymmetric: 12-col w/ a 7|5 split.
      */}
      <div style={{
        position: 'absolute', top: 36, left: 0, right: 0, bottom: 22,
        display: 'grid',
        gridTemplateColumns: 'repeat(12, 1fr)',
        gridTemplateRows: '170px 1fr',
      }}>

        {/* ----- HERO STRIP (left 7 cols) ----- */}
        <div style={{
          gridColumn: '1 / span 7', gridRow: '1', borderRight: TH, borderBottom: TH,
          padding: '12px 18px 10px',
          position: 'relative', overflow: 'hidden', minHeight: 0,
        }}>
          {hasActive ? <HeroActive P={P} ha={ha} item={lead} /> : <HeroQuiet P={P} ha={ha} now={now} />}
        </div>

        {/* ----- TIME + WEATHER (right 5 cols) ----- */}
        <div style={{
          gridColumn: '8 / span 5', gridRow: '1', borderBottom: TH,
          display: 'grid', gridTemplateRows: '1fr 1fr',
        }}>
          {/* Time */}
          <div style={{ padding: '10px 16px 8px', borderBottom: HL, position: 'relative' }}>
            <div style={{ ...SW_TY.cherrySmB, fontSize: 9, letterSpacing: '0.22em', color: P.muted }}>
              01 / TIME · LOCAL
            </div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 4, marginTop: -4 }}>
              <div style={{ ...SW_TY.display, fontSize: 64, lineHeight: 0.95 }}>
                {now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })}
              </div>
              <div style={{ ...SW_TY.cherryB, fontSize: 11, letterSpacing: '0.14em', color: P.muted }}>
                :{String(now.getSeconds()).padStart(2,'0')}
              </div>
            </div>
            <div style={{ ...SW_TY.cherrySmB, fontSize: 10, letterSpacing: '0.18em', marginTop: -2 }}>
              {now.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: '2-digit', year: 'numeric' }).toUpperCase()}
            </div>
          </div>
          {/* Outside */}
          <div style={{ padding: '8px 16px 8px', position: 'relative', display: 'grid', gridTemplateColumns: '1fr auto', alignItems: 'end', gap: 10 }}>
            <div>
              <div style={{ ...SW_TY.cherrySmB, fontSize: 9, letterSpacing: '0.22em', color: P.muted }}>
                02 / OUTSIDE · {(ha.weather?.state || '').replace(/_/g,' ').toUpperCase()}
              </div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 4 }}>
                <div style={{ ...SW_TY.display, fontSize: 56, lineHeight: 0.95 }}>
                  {Math.round(ha.weather?.temperature ?? 0)}
                </div>
                <div style={{ ...SW_TY.display, fontSize: 22, lineHeight: 1 }}>°F</div>
              </div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2, paddingBottom: 4, alignItems: 'flex-end' }}>
              <KvR P={P} k="WIND" v={`${Math.round(ha.weather?.windSpeed||0)} ${window.compass(ha.weather?.windBearing)}`} />
              <KvR P={P} k="HUM"  v={`${ha.weather?.humidity ?? '—'}%`} />
              <KvR P={P} k="PRES" v={`${(ha.weather?.pressure ?? 0).toFixed(2)}`} />
            </div>
          </div>
        </div>

        {/* ----- BOTTOM ROW ----- */}
        {/* Climate column (left 4) */}
        <div style={{ gridColumn: '1 / span 4', gridRow: '2', borderRight: TH,
                      padding: '12px 14px 8px', position: 'relative' }}>
          <SectionLabel P={P}>03 / CLIMATE</SectionLabel>
          <FloorRow P={P} ha={ha} />
          <div style={{ marginTop: 10, paddingTop: 10, borderTop: HL }}>
            <SubLabel P={P}>RADIANT · NEST</SubLabel>
            <RadiantBlock P={P} c={ha.climates.radiantMain} label="MAIN" />
            <RadiantBlock P={P} c={ha.climates.radiantApt} label="APT" />
          </div>
        </div>

        {/* Pool + Sauna middle column (4-7) */}
        <div style={{ gridColumn: '5 / span 4', gridRow: '2', borderRight: TH,
                      display: 'grid', gridTemplateRows: '1fr 1fr' }}>
          {/* Pool */}
          <div style={{ padding: '12px 14px', borderBottom: HL, position: 'relative',
                        background: ha.pool?.heating ? (P.red === '#000000' ? '#000' : P.red) : 'transparent',
                        color: ha.pool?.heating ? P.bg : P.ink }}>
            <SectionLabel P={P} invert={ha.pool?.heating}>
              04 / POOL{ha.pool?.heating ? ' · HEATING' : ha.pool?.pumpRunning ? ' · FILTERING' : ' · IDLE'}
            </SectionLabel>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 4, marginTop: 2 }}>
              <div style={{ ...SW_TY.display, fontSize: 50, lineHeight: 0.9 }}>
                {Math.round(ha.pool?.current ?? 0)}
              </div>
              <div style={{ ...SW_TY.display, fontSize: 18 }}>°F</div>
              <div style={{ ...SW_TY.cherrySmB, fontSize: 10, letterSpacing: '0.14em', marginLeft: 6, opacity: 0.8 }}>
                → {window.fmtTemp(ha.pool?.target)}
              </div>
            </div>
            <div style={{ ...SW_TY.cherrySmB, fontSize: 9, letterSpacing: '0.16em', marginTop: 2, opacity: 0.85 }}>
              AIR {window.fmtTemp(ha.pool?.air)} · {ha.pool?.freezeProtect ? 'FREEZE GUARD' : 'NO FREEZE'}
            </div>
          </div>
          {/* Sauna */}
          <div style={{ padding: '12px 14px', position: 'relative',
                        background: ha.sauna?.mode === 'heat' ? (P.red === '#000000' ? '#000' : P.red) : 'transparent',
                        color: ha.sauna?.mode === 'heat' ? P.bg : P.ink }}>
            <SectionLabel P={P} invert={ha.sauna?.mode === 'heat'}>
              05 / SAUNA{ha.sauna?.mode === 'heat' ? ' · HEATING' : ' · STANDBY'}
            </SectionLabel>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 4, marginTop: 2 }}>
              <div style={{ ...SW_TY.display, fontSize: 50, lineHeight: 0.9 }}>
                {Math.round(ha.sauna?.current ?? 0)}
              </div>
              <div style={{ ...SW_TY.display, fontSize: 18 }}>°F</div>
              <div style={{ ...SW_TY.cherrySmB, fontSize: 10, letterSpacing: '0.14em', marginLeft: 6, opacity: 0.8 }}>
                → {window.fmtTemp(ha.sauna?.target)}
              </div>
            </div>
            <div style={{ ...SW_TY.cherrySmB, fontSize: 9, letterSpacing: '0.16em', marginTop: 2, opacity: 0.85 }}>
              ELEMENTS {ha.sauna?.heaters || 0}/3 · DOOR {ha.sauna?.door ? 'OPEN' : 'CLOSED'} · {ha.sauna?.duration}m
            </div>
          </div>
        </div>

        {/* Occupancy column (8-12) */}
        <div style={{ gridColumn: '9 / span 4', gridRow: '2',
                      padding: '12px 14px 8px', position: 'relative' }}>
          <SectionLabel P={P}>06 / OCCUPANCY</SectionLabel>
          <div style={{ marginTop: 4 }}>
            {ha.people.map((p, i) => (
              <PersonRow key={i} P={P} p={p} last={i === ha.people.length-1}/>
            ))}
          </div>
          <div style={{ marginTop: 10, paddingTop: 10, borderTop: HL,
                        display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
            <StatusChip P={P} k="GARAGE" v={(ha.garage.state||'?').toUpperCase()}
              accent={ha.garage.state === 'open' ? P.red : null}/>
            <StatusChip P={P} k="WINDOWS" v={`${ha.openWindows.length} OPEN`}
              accent={ha.openWindows.length ? P.yellow : null}/>
          </div>
          <div style={{ marginTop: 8, paddingTop: 8, borderTop: HL }}>
            <SunStrip P={P} ha={ha} />
          </div>
        </div>
      </div>

      {/* === FOOTER (thin) === */}
      <div style={{
        position: 'absolute', bottom: 0, left: 0, right: 0, height: 22,
        borderTop: TH,
        display: 'grid', gridTemplateColumns: '120px 1fr 1fr 120px',
        alignItems: 'center',
        ...SW_TY.cherrySmB, fontSize: 10, letterSpacing: '0.16em', color: P.muted,
      }}>
        <span style={{ padding: '0 14px', borderRight: HL }}>SRC · HA·KBOS</span>
        <span style={{ padding: '0 14px', borderRight: HL }}>
          {hasActive
            ? <span style={{ color: P.red }}>▲ {active.length} ITEM{active.length>1?'S':''} REQUIRE ATTENTION</span>
            : '◇ ALL SYSTEMS NOMINAL'}
        </span>
        <span style={{ padding: '0 14px', borderRight: HL, textAlign: 'right' }}>
          ZONES HEATING {ha.allClimates?.filter(c=>c.action==='heating').length||0}/{ha.allClimates?.length||0}
        </span>
        <span style={{ padding: '0 14px', textAlign: 'right' }}>↻ {window.fmtTime(now).toUpperCase()}</span>
      </div>

      {/* Hairline corner registration marks (Swiss flourish) */}
      <Registration P={P} />
    </div>
  );
}

// ============================================================
// HERO — quiet & active states
// ============================================================
function HeroQuiet({ P, ha, now }) {
  const homeCount = ha.people.filter(p => p.state === 'home').length;
  return (
    <div style={{ height: '100%', display: 'grid', gridTemplateColumns: '1fr auto', columnGap: 16, alignItems: 'stretch' }}>
      <div>
        <div style={{ ...SW_TY.cherrySmB, fontSize: 9, letterSpacing: '0.22em', color: P.muted }}>
          00 / NOW · ALL CLEAR
        </div>
        <div style={{ ...SW_TY.display, fontSize: 56, lineHeight: 0.92, marginTop: 4 }}>
          Nothing<br/>running.
        </div>
        <div style={{ ...SW_TY.cherrySmB, fontSize: 11, letterSpacing: '0.14em', color: P.muted, marginTop: 8 }}>
          {homeCount}/{ha.people.length} HOME · {ha.openWindows.length} WIN OPEN · CLIMATE WITHIN BOUNDS
        </div>
      </div>
      {/* big numeral marker — outlined ink, e-ink safe */}
      <div style={{ ...SW_TY.display, fontSize: 160, lineHeight: 0.78,
                    color: 'transparent',
                    WebkitTextStroke: `1.5px ${P.ink}`,
                    alignSelf: 'flex-end',
                    fontWeight: 900, letterSpacing: '-0.06em' }}>
        00
      </div>
    </div>
  );
}

function HeroActive({ P, ha, item }) {
  const meta = describeActive(ha, item.kind, P);
  const accent = meta.accent;
  return (
    <div style={{ height: '100%', display: 'grid', gridTemplateColumns: '1fr 180px', columnGap: 14, alignItems: 'stretch', minHeight: 0, overflow: 'hidden' }}>
      <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between', minHeight: 0, overflow: 'hidden' }}>
        <div style={{ minHeight: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ width: 9, height: 9, background: accent }}/>
            <div style={{ ...SW_TY.cherrySmB, fontSize: 10, letterSpacing: '0.22em', color: accent }}>
              00 / NOW · {meta.eyebrow}
            </div>
          </div>
          <div style={{ ...SW_TY.display, fontSize: 30, lineHeight: 1.02, marginTop: 4, textWrap: 'balance' }}>
            {meta.headline}
          </div>
          <div style={{ ...SW_TY.cherrySmB, fontSize: 10, letterSpacing: '0.10em', color: P.muted, marginTop: 5, lineHeight: 1.35 }}>
            {meta.sub}
          </div>
        </div>
        {/* progress bar / temp bar */}
        <div style={{ marginTop: 6, flexShrink: 0 }}>
          {meta.bar}
        </div>
      </div>
      {/* big number block */}
      <div style={{ borderLeft: `0.75px solid ${P.rule}`, paddingLeft: 14,
                    display: 'flex', flexDirection: 'column', justifyContent: 'space-between', minHeight: 0, overflow: 'hidden' }}>
        <div>
          <div style={{ ...SW_TY.cherrySmB, fontSize: 9, letterSpacing: '0.22em', color: P.muted }}>
            {meta.bigLabel}
          </div>
          <div style={{ ...SW_TY.display, fontSize: 84, lineHeight: 0.85, color: accent, marginTop: 2 }}>
            {meta.big}
          </div>
        </div>
        <div style={{ ...SW_TY.cherrySmB, fontSize: 10, letterSpacing: '0.16em', color: P.muted }}>
          {meta.bigSub}
        </div>
      </div>
    </div>
  );
}

function describeActive(ha, kind, P) {
  if (kind === 'sauna') {
    const s = ha.sauna;
    const remaining = s.target && s.current ? Math.max(0, s.target - s.current) : null;
    return {
      eyebrow: 'SAUNA HEATING',
      accent: P.red,
      headline: <>Climbing to <span style={{ color: P.red }}>{Math.round(s.target)}°</span>{remaining ? <>, {Math.round(remaining)}° to go.</> : '.'}</>,
      sub: `${s.heaters||0}/3 elements · ${s.duration}m cycle · room ${window.fmtTemp(s.roomTemp)} ${Math.round(s.roomHumidity||0)}%RH · door ${s.door ? 'open' : 'closed'}`,
      big: `${Math.round(s.current)}°`,
      bigLabel: 'CABIN · NOW',
      bigSub: `→ ${window.fmtTemp(s.target)}`,
      bar: <SegBar P={P} from={60} to={Math.max(s.target||175,175)} now={s.current} target={s.target} accent={P.red} />,
    };
  }
  if (kind === 'washer') {
    return {
      eyebrow: 'WASHER RUNNING',
      accent: P.blue,
      headline: <>{(ha.washer.status||'').replace(/_/g,' ').replace(/\b\w/g,c=>c.toUpperCase())}.</>,
      sub: `Cycle #${ha.washer.cycles} · finishes ${window.fmtClockShort(ha.washer.remaining)}`,
      big: window.fmtRelTime(ha.washer.remaining, ha.fetchedAt) || '—',
      bigLabel: 'REMAINING',
      bigSub: 'CYCLE ACTIVE',
      bar: null,
    };
  }
  if (kind === 'washer-done') {
    return {
      eyebrow: 'WASHER DONE',
      accent: P.red,
      headline: <>Move to dryer.</>,
      sub: `Cycle #${ha.washer.cycles} finished ${window.fmtClockShort(ha.washer.lastNotification?.at)}`,
      big: '✓',
      bigLabel: 'COMPLETE',
      bigSub: window.fmtRelTime(ha.washer.lastNotification?.at, ha.fetchedAt)?.toUpperCase() || '—',
      bar: null,
    };
  }
  if (kind === 'dishwasher') {
    const dw = ha.dishwasher;
    const prog = dw.progress != null ? Math.round(dw.progress) : null;
    return {
      eyebrow: 'DISHWASHER',
      accent: P.blue,
      headline: <>{(dw.program||'').replace('dishcare_dishwasher_program_','').replace(/_/g,' ').replace(/\b\w/g,c=>c.toUpperCase())}.</>,
      sub: `Finishes ${window.fmtRelTime(dw.finishTime, ha.fetchedAt) || '—'}`,
      big: prog != null ? `${prog}%` : '—',
      bigLabel: 'COMPLETE',
      bigSub: window.fmtClockShort(dw.finishTime),
      bar: prog != null ? <SegBar P={P} from={0} to={100} now={prog} accent={P.blue} hideLabels /> : null,
    };
  }
  if (kind === 'pool-heating') {
    const p = ha.pool;
    return {
      eyebrow: 'POOL HEATING',
      accent: P.red,
      headline: <>Climbing to <span style={{ color: P.red }}>{Math.round(p.target)}°</span>.</>,
      sub: `Heat exchanger active · air ${window.fmtTemp(p.air)} · ${p.freezeProtect ? 'freeze guard on' : 'no freeze risk'}`,
      big: `${Math.round(p.current)}°`,
      bigLabel: 'WATER · NOW',
      bigSub: `→ ${window.fmtTemp(p.target)}`,
      bar: <SegBar P={P} from={50} to={Math.max(p.target||90,90)} now={p.current} target={p.target} accent={P.red} />,
    };
  }
  return { eyebrow: '—', accent: P.ink, headline: '—', sub: '', big: '—', bigLabel: '', bigSub: '', bar: null };
}

// ============================================================
// SEGMENT BAR — Swiss-style bar with target tick
// ============================================================
function SegBar({ P, from, to, now, target, accent, hideLabels }) {
  if (now == null) return null;
  const pct = Math.max(0, Math.min(1, (now - from) / (to - from)));
  const tpct = target != null ? Math.max(0, Math.min(1, (target - from) / (to - from))) : null;
  const segs = 36;
  const fill = Math.round(pct * segs);
  return (
    <div>
      <div style={{ position: 'relative', height: 10, border: `1px solid ${P.rule}`, display: 'flex', overflow: 'visible' }}>
        {Array.from({length: segs}).map((_,i) => (
          <div key={i} style={{
            flex: 1, height: '100%',
            background: i < fill ? accent : P.bg,
            borderRight: i < segs-1 ? `1px solid ${i < fill ? P.bg : P.rule}` : 'none',
            opacity: i < fill ? 1 : (i % 4 === 0 ? 0.5 : 0.18),
          }} />
        ))}
        {tpct != null && (
          <>
            <div style={{ position: 'absolute', top: -4, bottom: -4, left: `calc(${tpct*100}% - 1px)`, width: 2, background: P.ink }}/>
            <div style={{ position: 'absolute', top: -10, left: `calc(${tpct*100}% - 8px)`, ...SW_TY.cherrySmB, fontSize: 8, letterSpacing: '0.1em', color: P.ink }}>TGT</div>
          </>
        )}
      </div>
      {!hideLabels && (
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 3, ...SW_TY.cherrySmB, fontSize: 9, letterSpacing: '0.10em', color: P.muted }}>
          <span>{from}°</span>
          <span style={{ color: P.ink }}>NOW {Math.round(now)}°</span>
          <span>{to}°</span>
        </div>
      )}
    </div>
  );
}

// ============================================================
// RIGHT-COLUMN ATOMS
// ============================================================
function SectionLabel({ P, children, invert }) {
  return (
    <div style={{
      ...SW_TY.cherrySmB, fontSize: 9, letterSpacing: '0.22em',
      color: invert ? 'rgba(255,255,255,0.85)' : P.muted,
      marginBottom: 4,
    }}>{children}</div>
  );
}
function SubLabel({ P, children }) {
  return (
    <div style={{ ...SW_TY.cherrySmB, fontSize: 9, letterSpacing: '0.20em', color: P.muted, marginBottom: 4 }}>
      {children}
    </div>
  );
}

function FloorRow({ P, ha }) {
  const floors = [
    { key: 'third', label: '3F', temp: ha.temps.third },
    { key: 'second', label: '2F', temp: ha.temps.second },
    { key: 'first', label: '1F', temp: ha.temps.first },
    { key: 'basement', label: 'BS', temp: ha.temps.basement },
  ];
  // compute domain across temps for relative bars
  const vals = floors.map(f => f.temp).filter(v => v != null);
  const lo = Math.min(...vals) - 2, hi = Math.max(...vals) + 2;
  return (
    <div style={{ marginTop: 4 }}>
      {floors.map((f, i) => {
        const heatCount = ha.floorHeatCount ? ha.floorHeatCount(f.key) : 0;
        const heating = heatCount > 0;
        const pct = f.temp != null ? Math.max(0, Math.min(1, (f.temp - lo) / (hi - lo))) : 0;
        const accent = heating ? P.red : P.ink;
        return (
          <div key={i} style={{
            display: 'grid', gridTemplateColumns: '24px 1fr 56px',
            alignItems: 'center', gap: 8,
            padding: '5px 0',
            borderTop: i === 0 ? 'none' : `0.75px solid ${P.rule}`,
          }}>
            <div style={{ ...SW_TY.cherryB, fontSize: 13, letterSpacing: '0.06em' }}>{f.label}</div>
            <div style={{ position: 'relative', height: 6, border: `0.75px solid ${P.ink}`, boxSizing: 'border-box' }}>
              <div style={{ position: 'absolute', top: 0, left: 0, height: '100%', width: `${pct*100}%`, background: accent }}/>
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'baseline', gap: 4 }}>
              <span style={{ ...SW_TY.display, fontSize: 18, color: accent, lineHeight: 1 }}>
                {window.fmtTemp(f.temp).replace('°','')}
              </span>
              <span style={{ ...SW_TY.cherrySmB, fontSize: 9, letterSpacing: '0.14em',
                color: heating ? P.red : P.muted }}>
                {heating ? `H${heatCount}` : '○'}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function RadiantBlock({ P, c, label }) {
  if (!c) return null;
  const heating = c.action === 'heating';
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
      padding: '3px 0',
    }}>
      <span style={{ ...SW_TY.cherryB, fontSize: 11, letterSpacing: '0.16em', color: heating ? P.red : P.ink }}>
        {heating ? '●' : '○'} {label}
      </span>
      <span style={{ display: 'inline-flex', alignItems: 'baseline', gap: 5 }}>
        <span style={{ ...SW_TY.display, fontSize: 18, color: heating ? P.red : P.ink, lineHeight: 1 }}>
          {window.fmtTemp(c.current).replace('°','')}
        </span>
        <span style={{ ...SW_TY.cherrySmB, fontSize: 9, letterSpacing: '0.10em', color: P.muted }}>
          →{window.fmtTemp(c.target).replace('°','')}
        </span>
      </span>
    </div>
  );
}

function PersonRow({ P, p, last }) {
  const home = p.state === 'home';
  return (
    <div style={{
      display: 'grid', gridTemplateColumns: '1fr auto', alignItems: 'baseline',
      padding: '4px 0',
      borderBottom: last ? 'none' : `0.5px dotted ${P.rule}`,
    }}>
      <span style={{ ...SW_TY.sans, fontSize: 13, fontWeight: 500 }}>
        {p.name.split(' ')[0]}
      </span>
      <span style={{ ...SW_TY.cherryB, fontSize: 10, letterSpacing: '0.16em',
        color: home ? P.green : P.muted }}>
        {home ? '● HOME' : '○ ' + (p.state || 'AWAY').toUpperCase()}
      </span>
    </div>
  );
}

function StatusChip({ P, k, v, accent }) {
  return (
    <div style={{ border: `0.75px solid ${P.rule}`, padding: '4px 6px',
                  background: accent ? (accent === P.red ? P.red : 'transparent') : 'transparent',
                  color: accent === P.red ? P.bg : P.ink }}>
      <div style={{ ...SW_TY.cherrySmB, fontSize: 8, letterSpacing: '0.18em', opacity: 0.7 }}>{k}</div>
      <div style={{ ...SW_TY.cherryB, fontSize: 11, letterSpacing: '0.10em', color: accent && accent !== P.red ? accent : 'inherit' }}>{v}</div>
    </div>
  );
}

function SunStrip({ P, ha }) {
  const rise = window.fmtClockShort(ha.sun.nextRising || ha.sun.nextDawn);
  const set  = window.fmtClockShort(ha.sun.nextSetting || ha.sun.nextDusk);
  const above = ha.sun.state === 'above_horizon';
  return (
    <div>
      <SubLabel P={P}>SUN · {above ? 'ABOVE' : 'BELOW'}</SubLabel>
      <div style={{ display: 'flex', justifyContent: 'space-between', ...SW_TY.cherryB, fontSize: 11, letterSpacing: '0.10em', marginTop: 2 }}>
        <span>↑ {rise}</span>
        <span style={{ color: P.muted }}>──</span>
        <span>↓ {set}</span>
      </div>
    </div>
  );
}

function KvR({ P, k, v }) {
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
      <span style={{ ...SW_TY.cherrySmB, fontSize: 9, letterSpacing: '0.18em', color: P.muted }}>{k}</span>
      <span style={{ ...SW_TY.cherryB, fontSize: 11, letterSpacing: '0.06em' }}>{v}</span>
    </div>
  );
}

// Corner registration marks — small Swiss touch
function Registration({ P }) {
  const mark = (style) => (
    <div style={{ position: 'absolute', width: 8, height: 8, ...style }}>
      <div style={{ position: 'absolute', top: '50%', left: 0, right: 0, height: 1, background: P.muted }}/>
      <div style={{ position: 'absolute', left: '50%', top: 0, bottom: 0, width: 1, background: P.muted }}/>
    </div>
  );
  return (
    <>
      {/* none in corners — too noisy. keep a single tiny one in title bar slot to read as detail */}
    </>
  );
}

window.SwissDashboard = SwissDashboard;
window.SW_PALETTE = SW_PALETTE;
