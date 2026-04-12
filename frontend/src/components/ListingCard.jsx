import { useState } from 'react'
import MetroBadge from './MetroBadge.jsx'

const FURNISHING_COLOR = {
  furnished: 'bg-emerald-100 text-emerald-700',
  'semi-furnished': 'bg-yellow-100 text-yellow-700',
  unfurnished: 'bg-gray-100 text-gray-600',
}

const PLATFORM_LABEL = {
  '99acres': '99Acres',
  nobroker: 'NoBroker',
  housing: 'Housing',
  magicbricks: 'MagicBricks',
  squareyards: 'SquareYards',
  facebook: 'Facebook',
}

export default function ListingCard({ listing, apiBase }) {
  const [imgIdx, setImgIdx] = useState(0)
  const [enquiring, setEnquiring] = useState(false)
  const [enquired, setEnquired] = useState(false)

  const images = listing.images || []
  const furnColor = FURNISHING_COLOR[listing.furnishing] || 'bg-gray-100 text-gray-600'

  async function handleEnquire() {
    setEnquiring(true)
    try {
      const res = await fetch(`${apiBase}/enquire/${listing.id}`)
      const data = await res.json()
      if (data.wa_url) {
        window.open(data.wa_url, '_blank')
        setEnquired(true)
      }
    } catch (e) {
      alert('Could not open WhatsApp. Check if a contact number is available.')
    }
    setEnquiring(false)
  }

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden hover:shadow-md transition-shadow">
      {/* Image carousel */}
      <div className="relative h-48 bg-gray-100">
        {images.length > 0 ? (
          <img
            src={images[imgIdx]}
            alt={listing.title}
            className="w-full h-full object-cover"
            onError={e => { e.target.src = 'https://placehold.co/400x200/e2e8f0/94a3b8?text=No+Image' }}
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-gray-400 text-sm">No image</div>
        )}

        {/* Rank badge */}
        <span className="absolute top-2 left-2 bg-white text-gray-700 text-xs font-bold px-2 py-1 rounded-full shadow">
          #{listing.rank}
        </span>

        {/* Platform badge */}
        <span className="absolute top-2 right-2 bg-black/60 text-white text-xs px-2 py-1 rounded-full">
          {PLATFORM_LABEL[listing.platform] || listing.platform}
        </span>

        {/* Image nav */}
        {images.length > 1 && (
          <div className="absolute bottom-2 left-0 right-0 flex justify-center gap-1">
            {images.slice(0, 6).map((_, i) => (
              <button key={i} onClick={() => setImgIdx(i)}
                className={`w-1.5 h-1.5 rounded-full transition-colors ${i === imgIdx ? 'bg-white' : 'bg-white/50'}`}
              />
            ))}
          </div>
        )}
        {images.length > 1 && imgIdx < images.length - 1 && (
          <button onClick={() => setImgIdx(i => i + 1)}
            className="absolute right-2 top-1/2 -translate-y-1/2 bg-black/40 text-white rounded-full w-7 h-7 flex items-center justify-center text-xs hover:bg-black/60">
            ›
          </button>
        )}
        {images.length > 1 && imgIdx > 0 && (
          <button onClick={() => setImgIdx(i => i - 1)}
            className="absolute left-2 top-1/2 -translate-y-1/2 bg-black/40 text-white rounded-full w-7 h-7 flex items-center justify-center text-xs hover:bg-black/60">
            ‹
          </button>
        )}
      </div>

      {/* Details */}
      <div className="p-4">
        <div className="flex items-start justify-between gap-2 mb-1">
          <h3 className="text-sm font-semibold text-gray-800 line-clamp-1">{listing.title || 'Rental Flat'}</h3>
          <span className="text-base font-bold text-blue-600 whitespace-nowrap">
            ₹{listing.price ? listing.price.toLocaleString('en-IN') : '—'}
            <span className="text-xs font-normal text-gray-400">/mo</span>
          </span>
        </div>

        <p className="text-xs text-gray-500 mb-2 flex items-center gap-1">
          <span>📍</span>
          {listing.area || listing.address || 'Pune'}
        </p>

        {/* Tags */}
        <div className="flex flex-wrap gap-1 mb-2">
          {listing.furnishing && (
            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${furnColor}`}>
              {listing.furnishing}
            </span>
          )}
          {listing.occupancy && listing.occupancy !== 'any' && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 font-medium">
              {listing.occupancy} occupancy
            </span>
          )}
          {listing.brokerage === false && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-orange-100 text-orange-600 font-medium">
              No brokerage
            </span>
          )}
        </div>

        {/* Metro */}
        <MetroBadge
          station={listing.metro_station}
          walkingM={listing.walking_distance_m}
          travelMin={listing.metro_travel_min}
        />

        {/* Actions */}
        <div className="flex gap-2 mt-3">
          {listing.url && (
            <a href={listing.url} target="_blank" rel="noreferrer"
              className="flex-1 text-center text-xs border border-gray-300 text-gray-600 hover:bg-gray-50 py-2 rounded-lg transition-colors">
              View Listing
            </a>
          )}
          <button
            onClick={handleEnquire}
            disabled={enquiring || !listing.contact}
            className={`flex-1 text-xs font-semibold py-2 rounded-lg transition-colors flex items-center justify-center gap-1
              ${enquired
                ? 'bg-green-500 text-white'
                : listing.contact
                  ? 'bg-green-500 hover:bg-green-600 text-white'
                  : 'bg-gray-100 text-gray-400 cursor-not-allowed'
              }`}
          >
            {enquiring ? '...' : enquired ? '✓ Sent' : '💬 Enquire on WhatsApp'}
          </button>
        </div>

        {!listing.contact && (
          <p className="text-xs text-gray-400 mt-1 text-center">No phone number available</p>
        )}
      </div>
    </div>
  )
}
