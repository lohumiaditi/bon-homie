import { useState } from 'react'

const PUNE_AREAS = [
  'Aundh','Baner','Balewadi','Bavdhan','Bhosari','Camp','Chinchwad',
  'Deccan','Dhanori','Erandwane','Hadapsar','Hinjewadi','Karve Nagar',
  'Katraj','Khadki','Kharadi','Kondhwa','Koregaon Park','Kothrud',
  'Magarpatta','Mundhwa','Pashan','Pimpri','Pimple Saudagar','Ravet',
  'Sadashiv Peth','Sinhagad Road','Sus','Undri','Viman Nagar',
  'Vishrantwadi','Wadgaon Sheri','Wagholi','Wakad','Warje','Yerawada',
]

export default function SearchForm({ onSearch }) {
  const [areas, setAreas] = useState([])
  const [areaInput, setAreaInput] = useState('')
  const [budgetMin, setBudgetMin] = useState(8000)
  const [budgetMax, setBudgetMax] = useState(20000)
  const [furnishing, setFurnishing] = useState('any')
  const [renterType, setRenterType] = useState('any')
  const [gender, setGender] = useState('any')
  const [occupancy, setOccupancy] = useState('any')
  const [brokerage, setBrokerage] = useState('any')
  const [destination, setDestination] = useState('')
  const [loading, setLoading] = useState(false)
  const [suggestions, setSuggestions] = useState([])

  function handleAreaInput(val) {
    setAreaInput(val)
    if (val.length > 0) {
      setSuggestions(
        PUNE_AREAS.filter(a => a.toLowerCase().includes(val.toLowerCase())).slice(0, 6)
      )
    } else {
      setSuggestions([])
    }
  }

  function addArea(area) {
    if (!areas.includes(area)) setAreas([...areas, area])
    setAreaInput('')
    setSuggestions([])
  }

  function removeArea(area) {
    setAreas(areas.filter(a => a !== area))
  }

  async function handleSubmit(e) {
    e.preventDefault()
    if (areas.length === 0) return alert('Please add at least one area.')
    if (budgetMin > budgetMax) return alert('Min budget must be less than max.')
    setLoading(true)
    await onSearch({
      areas,
      budget_min: budgetMin,
      budget_max: budgetMax,
      furnishing,
      renter_type: renterType,
      gender,
      occupancy,
      brokerage,
      destination_address: destination || null,
    })
    setLoading(false)
  }

  const selectClass = "w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"

  return (
    <form onSubmit={handleSubmit} className="bg-white rounded-2xl shadow-md p-6 max-w-2xl mx-auto">
      <h2 className="text-lg font-semibold text-gray-800 mb-5">Find Your Flat in Pune</h2>

      {/* Areas */}
      <div className="mb-4 relative">
        <label className="block text-sm font-medium text-gray-700 mb-1">Areas <span className="text-red-500">*</span></label>
        <div className="flex flex-wrap gap-2 mb-2">
          {areas.map(a => (
            <span key={a} className="flex items-center gap-1 bg-blue-100 text-blue-700 text-xs font-medium px-2 py-1 rounded-full">
              {a}
              <button type="button" onClick={() => removeArea(a)} className="hover:text-red-500">×</button>
            </span>
          ))}
        </div>
        <input
          value={areaInput}
          onChange={e => handleAreaInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), areaInput && addArea(areaInput.trim()))}
          placeholder="Type area name (e.g. Kothrud)..."
          className={selectClass}
        />
        {suggestions.length > 0 && (
          <ul className="absolute z-10 bg-white border border-gray-200 rounded-lg shadow-lg mt-1 w-full text-sm">
            {suggestions.map(s => (
              <li key={s} onClick={() => addArea(s)}
                className="px-3 py-2 hover:bg-blue-50 cursor-pointer">{s}</li>
            ))}
          </ul>
        )}
      </div>

      {/* Budget */}
      <div className="grid grid-cols-2 gap-3 mb-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Min Rent (₹/mo)</label>
          <input type="number" value={budgetMin} onChange={e => setBudgetMin(+e.target.value)}
            min={1000} step={500} className={selectClass} />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Max Rent (₹/mo)</label>
          <input type="number" value={budgetMax} onChange={e => setBudgetMax(+e.target.value)}
            min={1000} step={500} className={selectClass} />
        </div>
      </div>

      {/* Filters row */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Furnishing</label>
          <select value={furnishing} onChange={e => setFurnishing(e.target.value)} className={selectClass}>
            <option value="any">Any</option>
            <option value="furnished">Furnished</option>
            <option value="semi-furnished">Semi-furnished</option>
            <option value="unfurnished">Unfurnished</option>
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Renter Type</label>
          <select value={renterType} onChange={e => setRenterType(e.target.value)} className={selectClass}>
            <option value="any">Any</option>
            <option value="family">Family</option>
            <option value="bachelor">Bachelor</option>
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Gender Pref.</label>
          <select value={gender} onChange={e => setGender(e.target.value)} className={selectClass}>
            <option value="any">Any</option>
            <option value="male">Male</option>
            <option value="female">Female</option>
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Occupancy</label>
          <select value={occupancy} onChange={e => setOccupancy(e.target.value)} className={selectClass}>
            <option value="any">Any</option>
            <option value="single">Single</option>
            <option value="double">Double / Sharing</option>
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Brokerage</label>
          <select value={brokerage} onChange={e => setBrokerage(e.target.value)} className={selectClass}>
            <option value="any">Any</option>
            <option value="no">No brokerage</option>
            <option value="yes">OK with brokerage</option>
          </select>
        </div>
      </div>

      {/* Destination */}
      <div className="mb-6">
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Your Destination <span className="text-gray-400 font-normal">(workplace / college — for metro time)</span>
        </label>
        <input value={destination} onChange={e => setDestination(e.target.value)}
          placeholder="e.g. Hinjewadi Phase 1, Pune"
          className={selectClass} />
      </div>

      <button type="submit" disabled={loading}
        className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white font-semibold py-3 rounded-xl text-sm transition-colors">
        {loading ? 'Starting search...' : '🔍 Find Flats'}
      </button>
    </form>
  )
}
