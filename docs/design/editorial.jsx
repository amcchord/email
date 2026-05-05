// EDITORIAL — 800x480 e-ink home dashboard.
// A magazine spread, not a newspaper: large flag, dramatic kicker hierarchy,
// drop cap on the lead, asymmetric column rhythm, ornaments earned through restraint.

const E_PALETTE = {
  six: {
    bg:   '#ffffff',
    ink:  '#111111',
    paper:'#f5efe4',
    red:  '#c8261b',
    blue: '#1d4d8a',
    green:'#1f6b3a',
    yellow:'#e7b800',
    rule: '#111111',
    soft: '#111111',  // hairlines only — no grey fills
    muted:'#111111',  // ink — e-ink can't render grey
  },
  bw: {
    bg:'#ffffff', ink:'#000000', paper:'#ffffff',
    red:'#000000', blue:'#000000', green:'#000000', yellow:'#000000',
    rule:'#000000', soft:'#000000', muted:'#000000',
  },
};

// ---- helpers ----
const fmtTemp = (v) => v == null ? '—' : `${Math.round(v)}°`;
const WEATHER_LABEL = {
  'partlycloudy':'Partly Cloudy', 'mostlycloudy':'Mostly Cloudy',
  'clear-night':'Clear Night', 'sunny':'Sunny', 'cloudy':'Cloudy',
  'rainy':'Rainy', 'snowy':'Snowy', 'windy':'Windy', 'fog':'Fog',
  'lightning':'Lightning', 'lightning-rainy':'Thunderstorm',
  'pouring':'Pouring', 'hail':'Hail', 'snowy-rainy':'Sleet',
};
const fmtWeather = (s) => WEATHER_LABEL[s] || (s || '').replace(/[-_]/g,' ').replace(/\b\w/g, c => c.toUpperCase());
const fmtTime = (d) => d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
const fmtDate = (d) => d.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' });
const fmtRelTime = (iso, now) => {
  if (!iso || iso === 'unknown' || iso === 'unavailable') return null;
  const t = new Date(iso); const n = now || new Date();
  const ms = t - n;
  if (ms < 0) {
    const m = Math.round(-ms / 60000);
    if (m < 1) return 'just now';
    if (m < 60) return `${m}m ago`;
    const h = Math.round(m/60);
    if (h < 24) return `${h}h ago`;
    return `${Math.round(h/24)}d ago`;
  }
  const m = Math.round(ms / 60000);
  if (m < 1) return 'now';
  if (m < 60) return `in ${m}m`;
  return `in ${Math.round(m/60)}h`;
};
const fmtDuration = (iso, now) => {
  if (!iso || iso === 'unknown' || iso === 'unavailable') return null;
  const ms = new Date(iso) - (now || new Date());
  if (ms <= 0) return null;
  const m = Math.round(ms / 60000);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m/60); const rem = m % 60;
  return rem ? `${h}h${rem}m` : `${h}h`;
};
const fmtClock = (iso) => iso ? new Date(iso).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }) : '—';
const compass = (deg) => deg == null ? '' : ['N','NE','E','SE','S','SW','W','NW'][Math.round(((deg % 360) / 45)) % 8];
const cleanProgram = (p) => (p||'').replace('dishcare_dishwasher_program_','').replace(/_/g,' ');
const titleCase = (s) => (s||'').replace(/_/g,' ').replace(/\b\w/g, c => c.toUpperCase());

function pickActive(ha, P) {
  const out = [];
  const s = ha.sauna;
  if (s && (s.mode === 'heat' || (s.heaters||0) > 0)) out.push({ kind: 'sauna', severity: 1, accent: P.red });
  const w = ha.washer;
  if (w?.status && !['power_off','end','initial','unavailable','unknown',null,''].includes(w.status)) {
    out.push({ kind: 'washer', severity: 2, accent: P.blue });
  } else if (w?.lastNotification?.type === 'washing_is_complete') {
    const ageHrs = (Date.now() - new Date(w.lastNotification.at).getTime()) / 3600000;
    if (ageHrs < 6) out.push({ kind: 'washer-done', severity: 1, accent: P.red });
  }
  const dw = ha.dishwasher;
  if (dw && ['run','delayedstart','pause','actionrequired','finished'].includes(dw.state)) {
    out.push({ kind: 'dishwasher', severity: dw.state === 'actionrequired' ? 1 : 3, accent: P.blue });
  }
  if (ha.pool?.heating) out.push({ kind: 'pool', severity: 3, accent: P.red });
  return out.sort((a,b) => a.severity - b.severity);
}

function heatingZoneCount(ha) {
  if (!ha.allClimates) return 0;
  return ha.allClimates.filter(c => c.action === 'heating').length;
}

// ---- typography presets ----
const TY = {
  serifHero:   { fontFamily: '"Source Serif 4", Georgia, serif', fontWeight: 700, letterSpacing: '-0.025em' },
  serifMed:    { fontFamily: '"Source Serif 4", Georgia, serif', fontWeight: 600, letterSpacing: '-0.005em' },
  serifLight:  { fontFamily: '"Source Serif 4", Georgia, serif', fontWeight: 400 },
  serifItalic: { fontFamily: '"Source Serif 4", Georgia, serif', fontStyle: 'italic', fontWeight: 400 },
  serifItalicB:{ fontFamily: '"Source Serif 4", Georgia, serif', fontStyle: 'italic', fontWeight: 700 },
  black:       { fontFamily: 'UnifrakturCook, "Source Serif 4", serif', fontWeight: 700 },
  cherry:      { fontFamily: '"Cherry", monospace', fontWeight: 400 },
  cherryB:     { fontFamily: '"Cherry", monospace', fontWeight: 700 },
  cherrySm:    { fontFamily: '"Cherry Small", monospace', fontWeight: 400 },
  cherrySmB:   { fontFamily: '"Cherry Small", monospace', fontWeight: 700 },
};

// =====================================================
// MAIN
// =====================================================
function EditorialDashboard({ ha, palette }) {
  const P = palette;
  const now = ha.fetchedAt;
  const active = pickActive(ha, P);
  const lead = active[0];

  return (
    <div style={{
      width: 800, height: 480, background: P.bg, color: P.ink,
      position: 'relative', overflow: 'hidden', boxSizing: 'border-box',
      fontFamily: '"Source Serif 4", Georgia, serif',
    }}>
      <Masthead P={P} now={now} weather={ha.weather} />

      {/* === BODY: 3-column with proper newspaper rhythm === */}
      <div style={{
        position: 'absolute', top: 92, left: 22, right: 22, bottom: 28,
        display: 'grid',
        gridTemplateColumns: '160px 1fr 168px',
        columnGap: 0,
      }}>
        <LeftRail P={P} ha={ha} />
        <LeadColumn P={P} ha={ha} lead={lead} rest={active.slice(1)} />
        <RightRail P={P} ha={ha} />
      </div>

      <Colophon P={P} ha={ha} now={now} />
    </div>
  );
}

// ---------- MASTHEAD ----------
// Newspaper flag: small dingbats flanking a stately wordmark, weather as the
// "edition" badge on the right. Underline rule is a heavy line + hairline.
function Masthead({ P, now, weather }) {
  const t = fmtTime(now); const [time, ampm] = t.split(' ');
  return (
    <div style={{
      position: 'absolute', top: 12, left: 22, right: 22, height: 70,
    }}>
      {/* top pin-rule */}
      <div style={{ height: 1, background: P.rule }}/>

      <div style={{
        display: 'grid',
        gridTemplateColumns: '170px 1fr 200px',
        alignItems: 'center',
        height: 56, padding: '0 4px',
      }}>
        {/* Time on the left, large but tight */}
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
          <div style={{ ...TY.serifHero, fontSize: 50, lineHeight: 0.85, letterSpacing: '-0.045em' }}>{time}</div>
          <div style={{ ...TY.serifItalic, fontSize: 17, color: P.muted }}>{ampm}</div>
        </div>

        {/* Center wordmark + simple date */}
        <div style={{ textAlign: 'center', position: 'relative' }}>
          <div style={{ ...TY.serifHero, fontSize: 32, lineHeight: 1, letterSpacing: '0.04em',
                        fontFamily: '"Source Serif 4", Georgia, serif' }}>
            CAMBRIDGE
          </div>
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10,
            ...TY.cherrySmB, fontSize: 10, letterSpacing: '0.22em', color: P.ink, marginTop: 5,
          }}>
            <span>{fmtDate(now).toUpperCase()}</span>
          </div>
        </div>

        {/* Outside as edition badge */}
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, justifyContent: 'flex-end' }}>
          <WeatherGlyph state={weather?.state} P={P} size={28} />
          <div style={{ textAlign: 'right' }}>
            <div style={{ ...TY.serifHero, fontSize: 50, lineHeight: 0.85, letterSpacing: '-0.045em' }}>
              {Math.round(weather?.temperature ?? 0)}°
            </div>
            <div style={{ ...TY.cherrySmB, fontSize: 10, letterSpacing: '0.16em', color: P.muted, marginTop: 3 }}>
              {fmtWeather(weather?.state).toUpperCase()}
            </div>
          </div>
        </div>
      </div>

      {/* heavy + hairline (newspaper convention) */}
      <div style={{ height: 3, background: P.rule }}/>
      <div style={{ height: 2 }}/>
      <div style={{ height: 1, background: P.rule }}/>
    </div>
  );
}

function Diamond({ P }) {
  return <span style={{ display: 'inline-block', width: 5, height: 5, transform: 'rotate(45deg)', background: P.ink }}/>;
}

// ---------- LEFT RAIL ----------
function LeftRail({ P, ha }) {
  const w = ha.weather;
  return (
    <div style={{ paddingRight: 14, borderRight: `0.75px solid ${P.rule}` }}>
      <Kicker P={P} text="Outside" decor />
      <div style={{ marginTop: 6 }}>
        <RailStat P={P} k="Wind"     v={`${Math.round(w?.windSpeed||0)}`} u={`mph ${compass(w?.windBearing)}`} />
        <RailStat P={P} k="Humidity" v={`${w?.humidity ?? '—'}`} u="%" />
        <RailStat P={P} k="Pressure" v={`${(w?.pressure||0).toFixed(2)}`} u="inHg" />
        <RailStat P={P} k="Visibility" v={`${Math.round(w?.visibility||0)}`} u="mi" />
      </div>

      <Hr P={P} mt={14} mb={8} />
      <Kicker P={P} text={`Sun · ${ha.sun.state === 'above_horizon' ? 'Risen' : 'Set'}`} decor />
      <SunArc P={P} ha={ha} />

      <Hr P={P} mt={12} mb={8} />
      <Kicker P={P} text="At Home" decor />
      <PeopleList P={P} people={ha.people} />
    </div>
  );
}

function RailStat({ P, k, v, u }) {
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
      padding: '3px 0',
      borderBottom: `0.5px dotted ${P.rule}`,
    }}>
      <span style={{ ...TY.serifItalic, fontSize: 13, color: P.ink }}>{k}</span>
      <span style={{ display: 'inline-flex', alignItems: 'baseline', gap: 3 }}>
        <b style={{ ...TY.serifHero, fontSize: 16, color: P.ink, lineHeight: 1 }}>{v}</b>
        <span style={{ ...TY.cherrySmB, fontSize: 9, letterSpacing: '0.10em', color: P.muted }}>{u}</span>
      </span>
    </div>
  );
}

function PeopleList({ P, people }) {
  return (
    <div style={{ marginTop: 4 }}>
      {people.slice(0, 5).map(p => (
        <div key={p.name} style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
          padding: '2px 0',
        }}>
          <span style={{ ...TY.serifMed, fontSize: 14 }}>{p.name.split(' ')[0]}</span>
          <span style={{ ...TY.cherrySmB, fontSize: 10, letterSpacing: '0.14em',
            color: p.state === 'home' ? P.green : P.muted }}>
            {p.state === 'home' ? '● home' : '○ ' + (p.state || 'away')}
          </span>
        </div>
      ))}
    </div>
  );
}

function SunArc({ P, ha }) {
  const rise = fmtClock(ha.sun.nextRising || ha.sun.nextDawn);
  const set  = fmtClock(ha.sun.nextSetting || ha.sun.nextDusk);
  const above = ha.sun.state === 'above_horizon';
  const now = ha.fetchedAt;
  let frac = 0.5;
  try {
    const r = new Date(ha.sun.nextRising || ha.sun.nextDawn);
    const s = new Date(ha.sun.nextSetting || ha.sun.nextDusk);
    if (above && s > now) {
      const rPrev = new Date(r.getTime() - 24*3600000);
      const total = s - rPrev;
      frac = total > 0 ? (now - rPrev) / total : 0.5;
    } else if (!above) frac = 0.0;
  } catch (e) {}
  frac = Math.max(0, Math.min(1, frac));
  const W = 138, H = 36;
  const cx = W/2, cy = H + 2, rX = W/2 - 8, rY = H - 8;
  const angle = Math.PI - frac * Math.PI;
  const sx = cx + rX * Math.cos(angle);
  const sy = cy - rY * Math.sin(angle);
  return (
    <div style={{ marginTop: 4 }}>
      <svg width={W} height={H+10} style={{ display: 'block' }}>
        <line x1={2} y1={H} x2={W-2} y2={H} stroke={P.ink} strokeWidth="1" />
        <path d={`M ${cx-rX},${cy} A ${rX} ${rY} 0 0 1 ${cx+rX},${cy}`}
              fill="none" stroke={P.ink} strokeWidth="0.75" strokeDasharray="1.5,2.5" />
        <circle cx={sx} cy={sy} r="4.5" fill={P.yellow !== '#000000' ? P.yellow : P.ink} stroke={P.ink} strokeWidth="1.25" />
        <line x1={cx-rX} y1={H-3} x2={cx-rX} y2={H+3} stroke={P.ink} strokeWidth="1.25" />
        <line x1={cx+rX} y1={H-3} x2={cx+rX} y2={H+3} stroke={P.ink} strokeWidth="1.25" />
      </svg>
      <div style={{ display: 'flex', justifyContent: 'space-between', ...TY.serifItalic, fontSize: 11, color: P.muted, marginTop: 1 }}>
        <span>↑ {rise}</span>
        <span>↓ {set}</span>
      </div>
    </div>
  );
}

// Weather glyph — pulled from prior design, lightly cleaner
function WeatherGlyph({ state, P, size = 24 }) {
  const ink = P.ink;
  const accent = P.yellow !== '#000000' ? P.yellow : P.ink;
  const blue = P.blue !== '#000000' ? P.blue : P.ink;
  if (!state) return null;
  const s = size;
  if (state.includes('clear-night')) {
    return <svg width={s} height={s} style={{display:'block'}}><circle cx={s*0.55} cy={s*0.45} r={s*0.32} fill="none" stroke={ink} strokeWidth="1.5"/><circle cx={s*0.7} cy={s*0.4} r={s*0.28} fill={P.bg}/></svg>;
  }
  if (state.includes('sunny') || state === 'clear') {
    return (
      <svg width={s} height={s} style={{display:'block'}}>
        <circle cx={s/2} cy={s/2} r={s*0.22} fill={accent} stroke={ink} strokeWidth="1.5"/>
        {[0,45,90,135,180,225,270,315].map(d => {
          const a = d * Math.PI / 180; const r1 = s*0.32, r2 = s*0.46;
          return <line key={d} x1={s/2+Math.cos(a)*r1} y1={s/2+Math.sin(a)*r1} x2={s/2+Math.cos(a)*r2} y2={s/2+Math.sin(a)*r2} stroke={ink} strokeWidth="1.5" strokeLinecap="round"/>;
        })}
      </svg>
    );
  }
  if (state.includes('cloud')) {
    return (
      <svg width={s} height={s} style={{display:'block'}}>
        {state.includes('partly') && <circle cx={s*0.32} cy={s*0.3} r={s*0.18} fill={accent} stroke={ink} strokeWidth="1.5"/>}
        <ellipse cx={s*0.55} cy={s*0.62} rx={s*0.32} ry={s*0.20} fill={P.bg} stroke={ink} strokeWidth="1.5"/>
        <ellipse cx={s*0.4} cy={s*0.55} rx={s*0.18} ry={s*0.14} fill={P.bg} stroke={ink} strokeWidth="1.5"/>
      </svg>
    );
  }
  if (state.includes('rain')) {
    return (
      <svg width={s} height={s} style={{display:'block'}}>
        <ellipse cx={s*0.5} cy={s*0.45} rx={s*0.32} ry={s*0.18} fill={P.bg} stroke={ink} strokeWidth="1.5"/>
        {[0.3,0.5,0.7].map((x,i) => <line key={i} x1={s*x} y1={s*0.65} x2={s*(x-0.05)} y2={s*0.9} stroke={blue} strokeWidth="1.5"/>)}
      </svg>
    );
  }
  return <svg width={s} height={s} style={{display:'block'}}><circle cx={s/2} cy={s/2} r={s*0.3} fill="none" stroke={ink} strokeWidth="1.5"/></svg>;
}

// ---------- LEAD COLUMN ----------
// One headline, treated like a magazine lead. Drop cap. Italic deck.
function LeadColumn({ P, ha, lead, rest }) {
  return (
    <div style={{ padding: '0 18px', display: 'flex', flexDirection: 'column', height: '100%' }}>
      {lead ? <Lead P={P} ha={ha} item={lead}/> : <CalmLead P={P} ha={ha}/>}
      {rest.length > 0 && (
        <>
          <DoubleHr P={P} mt={14} mb={8} />
          <Kicker P={P} text="Also Active" />
          <div style={{ marginTop: 6 }}>
            {rest.map((it, i) => <Brief key={i} P={P} item={it} ha={ha} last={i === rest.length-1}/>)}
          </div>
        </>
      )}
    </div>
  );
}

function CalmLead({ P, ha }) {
  return (
    <div>
      <div style={{ ...TY.cherrySmB, fontSize: 11, letterSpacing: '0.30em', color: P.muted }}>
        ★  THE CALM EDITION  ★
      </div>
      <div style={{ ...TY.serifHero, fontSize: 38, lineHeight: 0.95, marginTop: 8, textWrap: 'balance', letterSpacing: '-0.035em' }}>
        All quiet on the<br/>
        <span style={{ ...TY.serifItalicB }}>home front.</span>
      </div>
      <div style={{ ...TY.serifItalic, fontSize: 14, color: P.muted, marginTop: 8, lineHeight: 1.4 }}>
        Nothing running, nothing demanding.
      </div>
      <DoubleHr P={P} mt={14} mb={10} />
      <p style={{ ...TY.serifLight, fontSize: 13, lineHeight: 1.5, margin: 0, textWrap: 'pretty' }}>
        <DropCap P={P}>A</DropCap>ll appliances idle. Climate within bounds across the four floors. {ha.openWindows.length === 0
          ? 'All windows closed' : `${ha.openWindows.length} window${ha.openWindows.length>1?'s':''} open`}, garage {ha.garage.state || 'unknown'}.
      </p>
    </div>
  );
}

function Lead({ P, ha, item }) {
  if (item.kind === 'sauna')        return <SaunaLead P={P} ha={ha} accent={item.accent}/>;
  if (item.kind === 'washer')       return <WasherLead P={P} ha={ha} accent={item.accent}/>;
  if (item.kind === 'washer-done')  return <WasherDoneLead P={P} ha={ha} accent={item.accent}/>;
  if (item.kind === 'dishwasher')   return <DishwasherLead P={P} ha={ha} accent={item.accent}/>;
  if (item.kind === 'pool')         return <PoolLead P={P} ha={ha} accent={item.accent}/>;
  return null;
}

// Magazine-style lead with kicker, headline, italic deck, drop-cap body, stats strip
function StoryShell({ P, kicker, accent, headline, deck, body, stats, badge }) {
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <div style={{ width: 14, height: 14, background: accent, transform: 'rotate(45deg)' }}/>
        <div style={{ ...TY.cherrySmB, fontSize: 11, letterSpacing: '0.28em', color: accent }}>
          {kicker}
        </div>
        {badge && (
          <div style={{ marginLeft: 'auto', ...TY.cherrySmB, fontSize: 10, letterSpacing: '0.18em',
                        color: P.bg, background: accent, padding: '3px 8px' }}>
            {badge}
          </div>
        )}
      </div>
      <div style={{ ...TY.serifHero, fontSize: 32, lineHeight: 1.0, marginTop: 6, letterSpacing: '-0.03em', textWrap: 'balance' }}>
        {headline}
      </div>
      {deck && (
        <div style={{ ...TY.serifItalic, fontSize: 14, color: P.muted, marginTop: 4, lineHeight: 1.35 }}>
          {deck}
        </div>
      )}
      {body && (
        <p style={{ ...TY.serifLight, fontSize: 13, lineHeight: 1.5, margin: '8px 0 0 0', textWrap: 'pretty' }}>
          {body}
        </p>
      )}
      {stats}
    </div>
  );
}

function DropCap({ P, children }) {
  return (
    <span style={{
      ...TY.serifHero, fontSize: 36, lineHeight: 0.85,
      float: 'left', padding: '2px 6px 0 0', marginTop: 1,
      letterSpacing: '-0.04em',
    }}>{children}</span>
  );
}

function SaunaLead({ P, ha, accent }) {
  const s = ha.sauna;
  const remaining = s.target && s.current ? Math.max(0, s.target - s.current) : null;
  const head = (
    <>The sauna is <span style={{ color: accent, fontStyle: 'italic' }}>warming</span><br/>
      to {Math.round(s.target)}°.</>
  );
  const deck = remaining
    ? <>Cabin presently {Math.round(s.current)}°, with {Math.round(remaining)}° left to climb. {s.heaters||0} of three elements lit; door {s.door ? 'open' : 'closed'}.</>
    : <>Cabin holding at {Math.round(s.current)}°.</>;
  return (
    <div>
      <StoryShell P={P} kicker="Sauna · Heating" badge="LIVE" accent={accent}
        headline={head} deck={deck} />
      <div style={{ marginTop: 10 }}>
        <Thermometer P={P} from={60} to={Math.max(s.target||175, 175)} now={s.current} target={s.target} accent={accent} />
      </div>
      <FactStrip P={P} cells={[
        { k: 'Cabin', v: fmtTemp(s.current), accent },
        { k: 'Target', v: fmtTemp(s.target) },
        { k: 'Elements', v: `${s.heaters||0}/3` },
        { k: 'Room', v: fmtTemp(s.roomTemp), sub: `${Math.round(s.roomHumidity||0)}% RH` },
      ]} />
    </div>
  );
}

function WasherLead({ P, ha, accent }) {
  const w = ha.washer;
  const dur = fmtDuration(w.remaining, ha.fetchedAt);
  return (
    <div>
      <StoryShell P={P} kicker="Laundry · Running" accent={accent}
        headline={<>{titleCase(w.status)}<span style={{ ...TY.serifItalicB }}>, then spin.</span></>}
        deck={<>Cycle #{w.cycles}, finishing around {fmtClock(w.remaining)}. {dur ? `${dur} remaining.` : ''}</>}
      />
      <FactStrip P={P} cells={[
        { k: 'Remaining', v: dur || '—', accent },
        { k: 'Done by', v: fmtClock(w.remaining) },
        { k: 'Cycle', v: `#${w.cycles}` },
        { k: 'Mo. kWh', v: `${(w.energyMonth/1000||0).toFixed(2)}` },
      ]} />
    </div>
  );
}

function WasherDoneLead({ P, ha, accent }) {
  const w = ha.washer;
  return (
    <StoryShell P={P} kicker="Laundry · Attention" badge="UNLOAD" accent={accent}
      headline={<>Wash complete — <span style={{ ...TY.serifItalicB }}>please move<br/>to the dryer.</span></>}
      deck={<>Cycle #{w.cycles} finished {fmtClock(w.lastNotification?.at)} · {fmtRelTime(w.lastNotification?.at, ha.fetchedAt)}.</>}
      body={<>Cabin clean, drum still warm. The dryer awaits.</>}
    />
  );
}

function DishwasherLead({ P, ha, accent }) {
  const dw = ha.dishwasher;
  const prog = dw.progress != null ? Math.round(dw.progress) : null;
  return (
    <div>
      <StoryShell P={P} kicker="Dishwasher · Running" accent={accent}
        headline={<>{titleCase(cleanProgram(dw.program))} <span style={{ ...TY.serifItalicB }}>cycle.</span></>}
        deck={<>Finishing {fmtRelTime(dw.finishTime, ha.fetchedAt) || '—'} ({fmtClock(dw.finishTime)}). {prog != null ? `${prog}% complete.` : ''}</>}
      />
      {prog != null && (
        <div style={{ marginTop: 10 }}>
          <Thermometer P={P} from={0} to={100} now={prog} accent={accent} units="%" hideTarget />
        </div>
      )}
      <FactStrip P={P} cells={[
        { k: 'Progress', v: prog != null ? `${prog}%` : '—', accent },
        { k: 'Finish', v: fmtClock(dw.finishTime) },
        { k: 'Door', v: dw.door === 'closed' ? 'Closed' : titleCase(dw.door||'') },
      ]} />
    </div>
  );
}

function PoolLead({ P, ha, accent }) {
  const p = ha.pool;
  return (
    <div>
      <StoryShell P={P} kicker="Pool · Heating" accent={accent}
        headline={<>Climbing to <span style={{ color: accent, fontStyle: 'italic' }}>{Math.round(p.target)}°</span>.</>}
        deck={<>Heat exchanger active, water now {Math.round(p.current)}°. Air {Math.round(p.air)}°. {p.freezeProtect ? 'Freeze guard armed.' : 'No freeze risk.'}</>}
      />
      <div style={{ marginTop: 10 }}>
        <Thermometer P={P} from={50} to={Math.max(p.target||90, 90)} now={p.current} target={p.target} accent={accent}/>
      </div>
      <FactStrip P={P} cells={[
        { k: 'Water', v: fmtTemp(p.current), accent },
        { k: 'Target', v: fmtTemp(p.target) },
        { k: 'Air', v: fmtTemp(p.air) },
        { k: 'Pump', v: p.pumpRunning ? 'On' : 'Off' },
      ]} />
    </div>
  );
}

function FactStrip({ P, cells }) {
  return (
    <div style={{
      display: 'grid', gridTemplateColumns: `repeat(${cells.length}, 1fr)`,
      marginTop: 12,
      borderTop: `1.5px solid ${P.rule}`,
      borderBottom: `0.75px solid ${P.rule}`,
    }}>
      {cells.map((c, i) => (
        <div key={i} style={{
          padding: '6px 4px', textAlign: 'center',
          borderLeft: i === 0 ? 'none' : `0.5px solid ${P.rule}`,
        }}>
          <div style={{ ...TY.cherrySmB, fontSize: 9, letterSpacing: '0.18em', color: P.muted }}>{c.k.toUpperCase()}</div>
          <div style={{ ...TY.serifHero, fontSize: 19, lineHeight: 1.0, marginTop: 2, color: c.accent || P.ink, letterSpacing: '-0.02em' }}>
            {c.v}
          </div>
          {c.sub && (
            <div style={{ ...TY.cherrySmB, fontSize: 9, letterSpacing: '0.10em', color: P.muted, marginTop: 1 }}>
              {c.sub}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// Brief — secondary active items
function Brief({ P, item, ha, last }) {
  let title, sub, value;
  if (item.kind === 'sauna') {
    title = 'Sauna heating';
    sub = `${ha.sauna.heaters||0} elements · ${ha.sauna.duration}m cycle`;
    value = `${fmtTemp(ha.sauna.current)} → ${fmtTemp(ha.sauna.target)}`;
  } else if (item.kind === 'washer') {
    const dur = fmtDuration(ha.washer.remaining, ha.fetchedAt);
    title = `Washer · ${titleCase(ha.washer.status)}`;
    sub = `Cycle #${ha.washer.cycles} · finishes ${fmtClock(ha.washer.remaining)}`;
    value = dur ? `${dur} left` : '—';
  } else if (item.kind === 'washer-done') {
    title = 'Washer done';
    sub = `Cycle #${ha.washer.cycles}`;
    value = fmtRelTime(ha.washer.lastNotification?.at, ha.fetchedAt);
  } else if (item.kind === 'dishwasher') {
    title = 'Dishwasher running';
    sub = titleCase(cleanProgram(ha.dishwasher.program));
    value = ha.dishwasher.progress != null ? `${Math.round(ha.dishwasher.progress)}%` : '—';
  } else if (item.kind === 'pool') {
    title = 'Pool heating';
    sub = `Air ${fmtTemp(ha.pool.air)}`;
    value = `${fmtTemp(ha.pool.current)} → ${fmtTemp(ha.pool.target)}`;
  }
  return (
    <div style={{
      display: 'grid', gridTemplateColumns: '8px 1fr auto',
      alignItems: 'baseline', columnGap: 10,
      padding: '6px 0',
      borderBottom: last ? 'none' : `0.5px dotted ${P.rule}`,
    }}>
      <div style={{
        width: 6, height: 6, transform: 'translateY(2px) rotate(45deg)',
        background: item.accent,
      }}/>
      <div>
        <div style={{ ...TY.serifMed, fontSize: 14, lineHeight: 1.15 }}>{title}</div>
        <div style={{ ...TY.serifItalic, fontSize: 12, color: P.muted, marginTop: 1 }}>{sub}</div>
      </div>
      <div style={{ ...TY.serifHero, fontSize: 16, color: item.accent, textAlign: 'right' }}>{value}</div>
    </div>
  );
}

// ---------- RIGHT RAIL ----------
function RightRail({ P, ha }) {
  const p = ha.pool;
  return (
    <div style={{ paddingLeft: 16, borderLeft: `0.75px solid ${P.rule}` }}>
      <Kicker P={P} text="The House" decor />
      <FloorList P={P} ha={ha} />

      <Hr P={P} mt={10} mb={8} />
      <Kicker P={P} text="Hearth · Radiant" decor />
      <RadiantRow P={P} label="Main" c={ha.climates.radiantMain} />
      <RadiantRow P={P} label="Apt"  c={ha.climates.radiantApt} />

      <Hr P={P} mt={10} mb={8} />
      <Kicker P={P} text={`Pool · ${p?.heating ? 'Heating' : p?.pumpRunning ? 'Filtering' : 'Idle'}`} decor />
      <PoolMini P={P} p={p} />
    </div>
  );
}

function FloorList({ P, ha }) {
  const floors = [
    { key: 'third',    label: 'Third',     temp: ha.temps.third },
    { key: 'second',   label: 'Second',    temp: ha.temps.second },
    { key: 'first',    label: 'First',     temp: ha.temps.first },
    { key: 'basement', label: 'Basement',  temp: ha.temps.basement },
  ];
  return (
    <div style={{ marginTop: 4 }}>
      {floors.map((f, i) => {
        const heatCount = ha.floorHeatCount ? ha.floorHeatCount(f.key) : 0;
        const heating = heatCount > 0;
        return (
          <div key={i} style={{
            display: 'grid', gridTemplateColumns: '1fr auto',
            alignItems: 'baseline', gap: 6,
            padding: '4px 0',
            borderBottom: i === floors.length-1 ? 'none' : `0.5px dotted ${P.rule}`,
          }}>
            <div>
              <div style={{ ...TY.serifMed, fontSize: 13, lineHeight: 1.0 }}>{f.label}</div>
              <div style={{ ...TY.cherrySmB, fontSize: 9, letterSpacing: '0.16em',
                color: heating ? P.red : P.muted, marginTop: 2 }}>
                {heating ? `● ${heatCount} heat` : '○ idle'}
              </div>
            </div>
            <div style={{ ...TY.serifHero, fontSize: 22, lineHeight: 0.9,
              color: heating ? P.red : P.ink, letterSpacing: '-0.03em' }}>
              {fmtTemp(f.temp)}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function RadiantRow({ P, label, c }) {
  if (!c) return null;
  const heating = c.action === 'heating';
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
      padding: '2px 0',
    }}>
      <span style={{ ...TY.cherrySmB, fontSize: 10, letterSpacing: '0.14em', color: heating ? P.red : P.ink }}>
        {heating ? '●' : '○'} {label.toUpperCase()}
      </span>
      <span style={{ display: 'inline-flex', alignItems: 'baseline', gap: 5 }}>
        <span style={{ ...TY.serifHero, fontSize: 15, color: heating ? P.red : P.ink }}>{fmtTemp(c.current)}</span>
        {c.target && <span style={{ ...TY.cherrySmB, fontSize: 9, letterSpacing: '0.10em', color: P.muted }}>→{fmtTemp(c.target)}</span>}
      </span>
    </div>
  );
}

function PoolMini({ P, p }) {
  if (!p) return null;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 4 }}>
      <VerticalThermometer P={P} from={50} to={95} now={p.current} target={p.target}
        accent={p.heating ? P.red : P.blue} height={56} />
      <div style={{ flex: 1 }}>
        <div style={{ ...TY.serifHero, fontSize: 28, lineHeight: 0.85, letterSpacing: '-0.03em',
                      color: p.heating ? P.red : P.ink }}>
          {fmtTemp(p.current)}
        </div>
        <div style={{ ...TY.cherrySmB, fontSize: 9, letterSpacing: '0.14em', color: P.muted, marginTop: 4 }}>
          TGT {fmtTemp(p.target)}
        </div>
        <div style={{ ...TY.cherrySmB, fontSize: 9, letterSpacing: '0.14em', color: P.muted, marginTop: 1 }}>
          AIR {fmtTemp(p.air)}
        </div>
      </div>
    </div>
  );
}

// ---------- COLOPHON ----------
function Colophon({ P, ha, now }) {
  const homeNames = ha.people.filter(p => p.state === 'home').map(p => p.name.split(' ')[0]);
  const winColor = ha.openWindows.length ? (P.yellow !== '#000000' ? P.yellow : P.ink) : P.muted;
  const heatCount = heatingZoneCount(ha);
  return (
    <div style={{
      position: 'absolute', bottom: 0, left: 22, right: 22, height: 24,
      borderTop: `1.5px solid ${P.rule}`,
      display: 'grid', gridTemplateColumns: '1fr auto 1fr',
      alignItems: 'center', columnGap: 14,
      ...TY.cherrySmB, fontSize: 10, letterSpacing: '0.18em', whiteSpace: 'nowrap',
    }}>
      <div>
        {homeNames.length ? '● ' + homeNames.join(' & ').toUpperCase() + ' HOME' : '○ NOBODY HOME'}
      </div>
      <div style={{ ...TY.serifItalic, letterSpacing: '0.04em', fontSize: 11, color: P.muted }}>
        “All the news that fits the house.”
      </div>
      <div style={{ textAlign: 'right' }}>
        <span style={{ color: heatCount ? P.red : P.muted }}>{heatCount ? `● ${heatCount} ZONES` : '○ HVAC IDLE'}</span>
        <span style={{ color: P.muted }}> · </span>
        <span style={{ color: winColor }}>{ha.openWindows.length} WIN</span>
        <span style={{ color: P.muted }}> · </span>
        <span style={{ color: P.muted }}>↻ {fmtTime(now).toUpperCase()}</span>
      </div>
    </div>
  );
}

// =====================================================
// VISUALIZATIONS
// =====================================================
function Thermometer({ P, from, to, now, target, accent, hideTarget, units = '°' }) {
  if (now == null) return null;
  const pct = Math.max(0, Math.min(1, (now - from) / (to - from)));
  const tpct = (!hideTarget && target != null) ? Math.max(0, Math.min(1, (target - from) / (to - from))) : null;
  const segs = 32;
  const fill = Math.round(pct * segs);
  return (
    <div>
      <div style={{ position: 'relative', height: 12, border: `1.25px solid ${P.rule}`, display: 'flex', overflow: 'visible' }}>
        {Array.from({length: segs}).map((_,i) => (
          <div key={i} style={{
            flex: 1, height: '100%',
            background: i < fill ? accent : P.bg,
            borderRight: i < segs-1 ? `1px solid ${i < fill ? P.bg : P.rule}` : 'none',
            opacity: i < fill ? 1 : (i % 4 === 0 ? 0.5 : 0.18),
          }} />
        ))}
        {tpct != null && (
          <div style={{ position: 'absolute', top: -4, bottom: -4, left: `calc(${tpct*100}% - 1px)`, width: 2, background: P.ink }}/>
        )}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', ...TY.cherrySmB, fontSize: 9, letterSpacing: '0.10em', marginTop: 3, color: P.muted }}>
        <span>{from}{units}</span>
        <span style={{ color: P.ink }}>NOW {Math.round(now)}{units}</span>
        {!hideTarget && target != null && <span>TGT {Math.round(target)}{units}</span>}
        <span>{to}{units}</span>
      </div>
    </div>
  );
}

function VerticalThermometer({ P, from, to, now, target, accent, height = 60 }) {
  if (now == null) return null;
  const pct = Math.max(0, Math.min(1, (now - from) / (to - from)));
  const tpct = target != null ? Math.max(0, Math.min(1, (target - from) / (to - from))) : null;
  const segs = 12;
  const fill = Math.round(pct * segs);
  return (
    <div style={{ position: 'relative', width: 14, height, border: `1.25px solid ${P.rule}`, background: P.bg, display: 'flex', flexDirection: 'column-reverse' }}>
      {Array.from({length: segs}).map((_,i) => (
        <div key={i} style={{
          flex: 1, width: '100%',
          background: i < fill ? accent : P.bg,
          borderTop: i > 0 ? `1px solid ${i < fill ? P.bg : P.rule}` : 'none',
          opacity: i < fill ? 1 : (i % 4 === 0 ? 0.5 : 0.18),
        }} />
      ))}
      {tpct != null && (
        <div style={{ position: 'absolute', left: -4, right: -4, bottom: `calc(${tpct*100}% - 1px)`, height: 2, background: P.ink }}/>
      )}
    </div>
  );
}

// ---------- ATOMS ----------
function Kicker({ P, text, decor }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      {decor && <div style={{ width: 5, height: 5, background: P.ink, transform: 'rotate(45deg)' }}/>}
      <div style={{
        ...TY.cherrySmB, fontSize: 10, letterSpacing: '0.22em',
        textTransform: 'uppercase', color: P.ink,
      }}>{text}</div>
      {decor && <div style={{ flex: 1, height: 1, background: P.ink, marginLeft: 4 }}/>}
    </div>
  );
}
function Hr({ P, mt = 6, mb = 6 }) {
  return <div style={{ marginTop: mt, marginBottom: mb, borderTop: `0.75px solid ${P.rule}` }}/>;
}
function DoubleHr({ P, mt = 6, mb = 6 }) {
  return (
    <div style={{ marginTop: mt, marginBottom: mb }}>
      <div style={{ height: 2, background: P.rule }}/>
      <div style={{ height: 1.5 }}/>
      <div style={{ height: 0.75, background: P.rule }}/>
    </div>
  );
}

// Legacy shape used by swiss.jsx
function pickActiveSimple(ha) {
  const items = [];
  if (ha.sauna && (ha.sauna.mode === 'heat' || (ha.sauna.heaters||0) > 0)) items.push({ kind: 'sauna', priority: 1 });
  const w = ha.washer;
  if (w?.status && !['power_off','end','initial','unavailable','unknown',null,''].includes(w.status)) items.push({ kind: 'washer', priority: 2 });
  else if (w?.lastNotification?.type === 'washing_is_complete') {
    const ageHrs = (Date.now() - new Date(w.lastNotification.at).getTime()) / 3600000;
    if (ageHrs < 6) items.push({ kind: 'washer-done', priority: 2 });
  }
  const dw = ha.dishwasher;
  if (dw && ['run','delayedstart','pause','actionrequired','finished'].includes(dw.state)) items.push({ kind: 'dishwasher', priority: 3 });
  if (ha.pool?.heating) items.push({ kind: 'pool-heating', priority: 4 });
  return items.sort((a,b) => a.priority - b.priority);
}

window.EditorialDashboard = EditorialDashboard;
window.E_PALETTE = E_PALETTE;
window.pickActive = pickActiveSimple;
window.heatingZoneCount = heatingZoneCount;
window.fmtTemp = fmtTemp;
window.fmtTime = fmtTime;
window.fmtDate = fmtDate;
window.fmtRelTime = fmtRelTime;
window.fmtClockShort = fmtClock;
window.compass = compass;
