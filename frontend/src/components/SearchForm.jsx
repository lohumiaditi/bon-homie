import { useState } from 'react'

const PUNE_AREAS = [
  'Aundh','Baner','Balewadi','Bavdhan','Bhosari','Camp','Chinchwad',
  'Deccan','Dhanori','Dhayari','Erandwane','FC Road','Hadapsar',
  'Hinjewadi','Karve Nagar','Katraj','Khadki','Kharadi','Kondhwa',
  'Koregaon Park','Kothrud','Magarpatta','Mahalunge','Manjri',
  'Model Colony','Mundhwa','Nagar Road','Narhe','Pashan','Pimpri',
  'Pimple Nilakh','Pimple Saudagar','Ravet','Sadashiv Peth',
  'Salisbury Park','Sangvi','Sinhagad Road','Sus','Undri',
  'Viman Nagar','Vishrantwadi','Wadgaon Sheri','Wagholi','Wakad',
  'Warje','Yerawada',
]

// ── Reusable components ────────────────────────────────────────────────────
function Field({ label, hint, children }) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">
        {label}
        {hint && <span className="ml-1 text-xs text-gray-400 font-normal">{hint}</span>}
      </label>
      {children}
    </div>
  )
}

function Select({ value, onChange, options, placeholder }) {
  return (
    <select
      value={value}
      onChange={e => onChange(e.target.value)}
      className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent appearance-none cursor-pointer"
    >
      {placeholder && <option value="" disabled>{placeholder}</option>}
      {options.map(o => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  )
}

function AreaPicker({ areas, setAreas }) {
  const [input, setInput] = useState('')
  const [suggestions, setSuggestions] = useState([])

  function handleInput(val) {
    setInput(val)
    setSuggestions(
      val.length > 0
        ? PUNE_AREAS.filter(a => a.toLowerCase().includes(val.toLowerCase()) && !areas.includes(a)).slice(0, 6)
        : []
    )
  }

  function add(area) {
    if (!areas.includes(area)) setAreas([...areas, area])
    setInput('')
    setSuggestions([])
  }

  function remove(area) { setAreas(areas.filter(a => a !== area)) }

  return (
    <div className="relative">
      <div className="flex flex-wrap gap-1.5 mb-2 min-h-[28px]">
        {areas.map(a => (
          <span key={a} className="flex items-center gap-1 bg-blue-100 text-blue-700 text-xs font-medium px-2.5 py-1 rounded-full">
            {a}
            <button type="button" onClick={() => remove(a)} className="hover:text-red-500 leading-none">×</button>
          </span>
        ))}
        {areas.length === 0 && <span className="text-xs text-gray-400 mt-1">No areas selected yet</span>}
      </div>
      <input
        value={input}
        onChange={e => handleInput(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); if (input.trim()) add(input.trim()) } }}
        placeholder="Type to search areas (e.g. Kothrud)..."
        className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
      {suggestions.length > 0 && (
        <ul className="absolute z-20 bg-white border border-gray-200 rounded-xl shadow-lg mt-1 w-full text-sm overflow-hidden">
          {suggestions.map(s => (
            <li key={s} onClick={() => add(s)}
              className="px-4 py-2.5 hover:bg-blue-50 cursor-pointer flex items-center gap-2">
              <span className="text-blue-400">+</span> {s}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ── Section header ─────────────────────────────────────────────────────────
function Section({ icon, title, children }) {
  return (
    <div className="border border-gray-100 rounded-2xl p-4 space-y-4">
      <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider flex items-center gap-2">
        <span>{icon}</span>{title}
      </p>
      {children}
    </div>
  )
}

// ── Main form ──────────────────────────────────────────────────────────────
export default function SearchForm({ onSearch }) {
  // Step 1: type of accommodation
  const [flatType, setFlatType] = useState('')  // 'whole' | 'preoccupied'

  // Common fields
  const [areas, setAreas] = useState([])
  const [budgetMin, setBudgetMin] = useState('8000')
  const [budgetMax, setBudgetMax] = useState('20000')
  const [furnishing, setFurnishing] = useState('any')
  const [brokerage, setBrokerage] = useState('any')
  const [destination, setDestination] = useState('')

  // Whole-flat specific
  const [renterType, setRenterType] = useState('any')      // family | bachelor | any
  const [ownerGenderPref, setOwnerGenderPref] = useState('any') // what owner prefers

  // Pre-occupied specific
  const [occupancy, setOccupancy] = useState('single')     // single | double
  const [myGender, setMyGender] = useState('')             // male | female (you)
  const [flatmateGender, setFlatmateGender] = useState('any') // preferred flatmate gender

  const [loading, setLoading] = useState(false)
  const [errors, setErrors] = useState({})

  function validate() {
    const e = {}
    if (!flatType) e.flatType = 'Please select what you are looking for'
    if (areas.length === 0) e.areas = 'Add at least one area'
    if (!budgetMin || !budgetMax) e.budget = 'Enter your budget range'
    if (+budgetMin > +budgetMax) e.budget = 'Min budget must be less than max'
    if (flatType === 'preoccupied' && !myGender) e.myGender = 'Please select your gender'
    setErrors(e)
    return Object.keys(e).length === 0
  }

  async function handleSubmit(e) {
    e.preventDefault()
    if (!validate()) return
    setLoading(true)

    const payload = {
      flat_type: flatType,
      areas,
      budget_min: +budgetMin,
      budget_max: +budgetMax,
      furnishing,
      brokerage,
      destination_address: destination || null,
      // normalise to API contract
      renter_type: flatType === 'whole' ? renterType : 'any',
      gender: flatType === 'whole' ? ownerGenderPref : myGender,
      occupancy: flatType === 'preoccupied' ? occupancy : 'any',
      flatmate_gender: flatType === 'preoccupied' ? flatmateGender : 'any',
    }

    await onSearch(payload)
    setLoading(false)
  }

  // ── Flat type cards ──
  const typeCards = [
    {
      value: 'whole',
      icon: '🏠',
      title: 'Entire Flat',
      desc: 'You rent the whole flat — for yourself, family, or friends. No existing tenants.',
    },
    {
      value: 'preoccupied',
      icon: '🤝',
      title: 'Shared / Pre-occupied',
      desc: 'Move into a flat that already has tenants. Single room or double sharing.',
    },
  ]

  return (
    <form onSubmit={handleSubmit} className="max-w-2xl mx-auto space-y-5">

      {/* ── Step 1: What are you looking for? ── */}
      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
        <h2 className="text-base font-semibold text-gray-800 mb-1">Find your flat in Pune</h2>
        <p className="text-sm text-gray-400 mb-5">Answer a few questions and we'll search across 6 platforms for you.</p>

        <Field label="What are you looking for?" hint="*">
          <div className="grid grid-cols-2 gap-3 mt-1">
            {typeCards.map(card => (
              <button
                key={card.value}
                type="button"
                onClick={() => { setFlatType(card.value); setErrors(p => ({...p, flatType: ''})) }}
                className={`text-left p-4 rounded-xl border-2 transition-all ${
                  flatType === card.value
                    ? 'border-blue-500 bg-blue-50'
                    : 'border-gray-200 hover:border-gray-300 bg-white'
                }`}
              >
                <span className="text-2xl block mb-1">{card.icon}</span>
                <p className="text-sm font-semibold text-gray-800">{card.title}</p>
                <p className="text-xs text-gray-500 mt-0.5 leading-snug">{card.desc}</p>
              </button>
            ))}
          </div>
          {errors.flatType && <p className="text-xs text-red-500 mt-1">{errors.flatType}</p>}
        </Field>
      </div>

      {/* ── Shown only after flat type is selected ── */}
      {flatType && (
        <>
          {/* Location & Budget */}
          <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6 space-y-4">
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider">📍 Location & Budget</p>

            <Field label="Preferred areas" hint="(select one or more)">
              <AreaPicker areas={areas} setAreas={areas => { setAreas(areas); setErrors(p=>({...p,areas:''})) }} />
              {errors.areas && <p className="text-xs text-red-500 mt-1">{errors.areas}</p>}
            </Field>

            <div className="grid grid-cols-2 gap-3">
              <Field label="Min rent (₹/month)">
                <input
                  type="number" value={budgetMin}
                  onChange={e => { setBudgetMin(e.target.value); setErrors(p=>({...p,budget:''})) }}
                  min={1000} step={500}
                  className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </Field>
              <Field label="Max rent (₹/month)">
                <input
                  type="number" value={budgetMax}
                  onChange={e => { setBudgetMax(e.target.value); setErrors(p=>({...p,budget:''})) }}
                  min={1000} step={500}
                  className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </Field>
            </div>
            {errors.budget && <p className="text-xs text-red-500">{errors.budget}</p>}
          </div>

          {/* ── Whole flat specific ── */}
          {flatType === 'whole' && (
            <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6 space-y-4">
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider">🏠 Flat Preferences</p>

              <div className="grid grid-cols-2 gap-3">
                <Field label="Who will live here?">
                  <Select value={renterType} onChange={setRenterType} options={[
                    { value: 'any',      label: 'Any' },
                    { value: 'family',   label: 'Family' },
                    { value: 'bachelor', label: 'Bachelor / Single' },
                  ]} />
                </Field>

                <Field label="Gender preference" hint="(owner's requirement)">
                  <Select value={ownerGenderPref} onChange={setOwnerGenderPref} options={[
                    { value: 'any',    label: 'No preference' },
                    { value: 'male',   label: 'Male tenant only' },
                    { value: 'female', label: 'Female tenant only' },
                  ]} />
                </Field>

                <Field label="Furnishing">
                  <Select value={furnishing} onChange={setFurnishing} options={[
                    { value: 'any',            label: 'Any' },
                    { value: 'furnished',       label: 'Fully furnished' },
                    { value: 'semi-furnished',  label: 'Semi-furnished' },
                    { value: 'unfurnished',     label: 'Unfurnished' },
                  ]} />
                </Field>

                <Field label="Brokerage">
                  <Select value={brokerage} onChange={setBrokerage} options={[
                    { value: 'any', label: 'Any' },
                    { value: 'no',  label: 'No brokerage only' },
                    { value: 'yes', label: 'OK with brokerage' },
                  ]} />
                </Field>
              </div>
            </div>
          )}

          {/* ── Pre-occupied / Shared flat specific ── */}
          {flatType === 'preoccupied' && (
            <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6 space-y-4">
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider">🤝 Room & Flatmate Preferences</p>

              <div className="grid grid-cols-2 gap-3">
                <Field label="Room type">
                  <Select value={occupancy} onChange={setOccupancy} options={[
                    { value: 'single', label: 'Single occupancy (own room)' },
                    { value: 'double', label: 'Double sharing (split room)' },
                  ]} />
                </Field>

                <Field label="Your gender" hint="*">
                  <Select
                    value={myGender}
                    onChange={v => { setMyGender(v); setErrors(p=>({...p,myGender:''})) }}
                    placeholder="Select your gender"
                    options={[
                      { value: 'male',   label: 'Male' },
                      { value: 'female', label: 'Female' },
                    ]}
                  />
                  {errors.myGender && <p className="text-xs text-red-500 mt-1">{errors.myGender}</p>}
                </Field>

                <Field label="Preferred flatmate gender">
                  <Select value={flatmateGender} onChange={setFlatmateGender} options={[
                    { value: 'any',    label: 'No preference' },
                    { value: 'same',   label: 'Same as me' },
                    { value: 'male',   label: 'Male flatmates' },
                    { value: 'female', label: 'Female flatmates' },
                  ]} />
                </Field>

                <Field label="Furnishing">
                  <Select value={furnishing} onChange={setFurnishing} options={[
                    { value: 'any',           label: 'Any' },
                    { value: 'furnished',      label: 'Fully furnished' },
                    { value: 'semi-furnished', label: 'Semi-furnished' },
                    { value: 'unfurnished',    label: 'Unfurnished' },
                  ]} />
                </Field>

                <Field label="Brokerage">
                  <Select value={brokerage} onChange={setBrokerage} options={[
                    { value: 'any', label: 'Any' },
                    { value: 'no',  label: 'No brokerage only' },
                    { value: 'yes', label: 'OK with brokerage' },
                  ]} />
                </Field>
              </div>
            </div>
          )}

          {/* ── Destination ── */}
          <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-4">🚇 Commute (optional)</p>
            <Field label="Your destination" hint="— we'll calculate metro travel time from each flat">
              <input
                value={destination}
                onChange={e => setDestination(e.target.value)}
                placeholder="e.g. Hinjewadi Phase 1 / Shivajinagar / Magarpatta City"
                className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </Field>
          </div>

          {/* ── Submit ── */}
          <button
            type="submit"
            disabled={loading}
            className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white font-semibold py-3.5 rounded-2xl text-sm transition-colors shadow-sm"
          >
            {loading ? (
              <span className="flex items-center justify-center gap-2">
                <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/>
                </svg>
                Starting search across 6 platforms...
              </span>
            ) : '🔍  Find Flats'}
          </button>
        </>
      )}
    </form>
  )
}
