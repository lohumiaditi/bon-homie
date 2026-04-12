export default function MetroBadge({ station, walkingM, travelMin }) {
  if (!station) return null

  const walkKm = walkingM >= 1000
    ? `${(walkingM / 1000).toFixed(1)} km`
    : `${walkingM} m`

  return (
    <div className="flex flex-wrap gap-2 mt-2">
      <span className="inline-flex items-center gap-1 bg-purple-100 text-purple-700 text-xs font-medium px-2 py-1 rounded-full">
        🚇 {station}
      </span>
      <span className="inline-flex items-center gap-1 bg-green-100 text-green-700 text-xs font-medium px-2 py-1 rounded-full">
        🚶 {walkKm} walk
      </span>
      {travelMin != null && (
        <span className="inline-flex items-center gap-1 bg-blue-100 text-blue-700 text-xs font-medium px-2 py-1 rounded-full">
          ⏱ {travelMin} min to destination
        </span>
      )}
    </div>
  )
}
