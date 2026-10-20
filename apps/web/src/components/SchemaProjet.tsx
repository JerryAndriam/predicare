export function SchemaProjet() {
  return (
    <section aria-label="Schema du projet PrediCare" style={{ marginTop: '1rem' }}>
      <h3 style={{ fontSize: '1rem', letterSpacing: '-0.01em', marginBottom: '0.8rem', color: 'var(--primaire-fonce)' }}>
        Architecture du projet
      </h3>
      <svg viewBox="0 0 720 260" xmlns="http://www.w3.org/2000/svg" style={{ maxWidth: '100%', height: 'auto', borderRadius: 'var(--rayon)', background: 'var(--surface-degrade)', border: '1px solid var(--bord)', boxShadow: 'var(--ombre)' }}>
        <defs>
          <linearGradient id="blocGrd" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#ffffff" />
            <stop offset="100%" stopColor="#f8fafc" />
          </linearGradient>
          <filter id="softShadow" x="-20%" y="-20%" width="140%" height="140%">
            <feDropShadow dx="0" dy="2" stdDeviation="3" floodColor="#000000" floodOpacity="0.08" />
          </filter>
        </defs>

        {/* Blocs */}
        {[
          { x: 20,  y: 20,  w: 130, h: 46, label: 'data/raw (CSV)', sub: '14 fichiers', tone: '#0e1a27' },
          { x: 200, y: 20,  w: 130, h: 46, label: 'seed', sub: 'DB PostgreSQL', tone: '#0f766e' },
          { x: 380, y: 20,  w: 130, h: 46, label: 'pro (web)', sub: 'depose facture', tone: '#b42318' },
          { x: 200, y: 110, w: 130, h: 46, label: 'api-inference', sub: 'XGBoost v2', tone: '#0f766e' },
          { x: 380, y: 110, w: 130, h: 46, label: 'gestionnaire', sub: 'file d\'alertes', tone: '#1d4ed8' },
          { x: 560, y: 20,  w: 120, h: 46, label: 'audit / journal', sub: 'trace complete', tone: '#0e1a27' },
        ].map((b, i) => (
          <g key={i} filter="url(#softShadow)">
            <rect x={b.x} y={b.y} width={b.w} height={b.h} rx="10" fill="url(#blocGrd)" stroke={b.tone} strokeWidth="1.5" />
            <text x={b.x + b.w/2} y={b.y + 18} textAnchor="middle" fontSize="9" fontWeight="700" fill={b.tone} fontFamily="system-ui, sans-serif">{b.label}</text>
            <text x={b.x + b.w/2} y={b.y + 34} textAnchor="middle" fontSize="7.5" fill="#5b6776" fontFamily="system-ui, sans-serif">{b.sub}</text>
          </g>
        ))}

        {/* Fleches */}
        <g stroke="#dde3eb" strokeWidth="2" fill="none" strokeLinecap="round" strokeDasharray="4 3">
          <line x1="150" y1="43" x2="195" y2="43" />
          <line x1="330" y1="43" x2="375" y2="43" />
          <line x1="510" y1="43" x2="555" y2="43" />
          <line x1="265" y1="66" x2="265" y2="105" />
          <line x1="445" y1="66" x2="445" y2="105" />
        </g>
        {/* Pointes */}
        <g fill="#dde3eb">
          <polygon points="195,43 200,39 200,47" />
          <polygon points="375,43 380,39 380,47" />
          <polygon points="555,43 560,39 560,47" />
          <polygon points="265,105 261,100 269,100" />
          <polygon points="445,105 441,100 449,100" />
        </g>

        {/* Labels flux */}
        <text x="170" y="36" textAnchor="middle" fontSize="7" fill="#5b6776">chargement</text>
        <text x="345" y="36" textAnchor="middle" fontSize="7" fill="#5b6776">soumission</text>
        <text x="530" y="36" textAnchor="middle" fontSize="7" fill="#5b6776">audit</text>
        <text x="255" y="92" textAnchor="middle" fontSize="7" fill="#5b6776">prediction</text>
        <text x="435" y="92" textAnchor="middle" fontSize="7" fill="#5b6776">decision</text>

        {/* Légende */}
        <text x="360" y="240" textAnchor="middle" fontSize="8" fill="#0e1a27" fontWeight="600">Flux complet : donnees → modele → alerte → decision → audit</text>
      </svg>
    </section>
  )
}
