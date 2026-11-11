/** Two cups of chai on a quiet morning: an invitation to sit and talk, not a fight. */
export function CalmScene({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 360 230" role="img" aria-label="Two cups of chai on a quiet morning" className={className}>
      <defs>
        <linearGradient id="calm-sky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#f6dfbd" />
          <stop offset="1" stopColor="#f7eedf" />
        </linearGradient>
        <clipPath id="calm-frame">
          <rect width="360" height="230" rx="32" />
        </clipPath>
      </defs>
      <g clipPath="url(#calm-frame)">
        <rect width="360" height="230" fill="url(#calm-sky)" />
        {/* Morning sun */}
        <circle cx="254" cy="88" r="46" fill="#eeb486" opacity="0.45" />
        <circle cx="254" cy="88" r="28" fill="#e58f57" opacity="0.55" />
        {/* Birds */}
        <path d="M78 62 q7 -7 14 0 q7 -7 14 0" fill="none" stroke="#6b5e52" strokeWidth="2" strokeLinecap="round" opacity="0.5" />
        <path d="M112 44 q5 -5 10 0 q5 -5 10 0" fill="none" stroke="#6b5e52" strokeWidth="1.6" strokeLinecap="round" opacity="0.4" />
        {/* Hills */}
        <path d="M0 140 C60 112 120 118 180 134 S300 150 360 122 V230 H0Z" fill="#cfd6c6" />
        <path d="M0 162 C70 140 140 150 200 162 S310 176 360 156 V230 H0Z" fill="#a7b8aa" />
        {/* Ground */}
        <path d="M0 186 C90 178 270 178 360 186 V230 H0Z" fill="#2c4a45" />
        {/* Left cup */}
        <g>
          <path className="calm-steam" d="M134 150 c-7 -9 7 -13 0 -23" fill="none" stroke="#a89377" strokeWidth="2.4" strokeLinecap="round" />
          <path className="calm-steam calm-steam-late" d="M146 152 c-6 -8 6 -12 0 -20" fill="none" stroke="#a89377" strokeWidth="2" strokeLinecap="round" />
          <path d="M120 158 h42 v16 a15 15 0 0 1 -15 15 h-12 a15 15 0 0 1 -15 -15 z" fill="#fffaf2" />
          <path d="M162 164 a8 8 0 0 1 0 16" fill="none" stroke="#fffaf2" strokeWidth="4.5" />
          <rect x="120" y="168" width="42" height="4" fill="#c45c26" opacity="0.8" />
          <ellipse cx="141" cy="158" rx="21" ry="3.6" fill="#b5743f" />
        </g>
        {/* Right cup */}
        <g>
          <path className="calm-steam calm-steam-late" d="M214 150 c-7 -9 7 -13 0 -23" fill="none" stroke="#a89377" strokeWidth="2.4" strokeLinecap="round" />
          <path className="calm-steam" d="M226 152 c-6 -8 6 -12 0 -20" fill="none" stroke="#a89377" strokeWidth="2" strokeLinecap="round" />
          <path d="M200 158 h42 v16 a15 15 0 0 1 -15 15 h-12 a15 15 0 0 1 -15 -15 z" fill="#fffaf2" />
          <path d="M200 164 a8 8 0 0 0 0 16" fill="none" stroke="#fffaf2" strokeWidth="4.5" />
          <rect x="200" y="168" width="42" height="4" fill="#2c4a45" opacity="0.55" />
          <ellipse cx="221" cy="158" rx="21" ry="3.6" fill="#b5743f" />
        </g>
        {/* A small plant between them */}
        <path d="M181 189 v-20" stroke="#e8c9a8" strokeWidth="2" />
        <path d="M181 176 c-9 -2 -12 -9 -11 -15 c8 1 12 8 11 15z" fill="#e8c9a8" />
        <path d="M181 172 c8 -2 11 -9 10 -15 c-7 1 -11 8 -10 15z" fill="#e8c9a8" opacity="0.85" />
      </g>
    </svg>
  );
}
