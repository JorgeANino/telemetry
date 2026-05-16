import { useEffect, useRef, useState } from 'react';
import './App.css';
import { API_BASE, POLL_MS, usePolledJson } from './usePolledJson';

// --------------------------------------------------------------------------- //
// Types — kept in this file because the surface is tiny.                      //
// --------------------------------------------------------------------------- //

type Status = 'idle' | 'moving' | 'charging' | 'fault';

interface Vehicle {
  vehicle_id: string;
  status: Status;
  battery_pct: number | null;
  last_timestamp: string | null;
}

interface Anomaly {
  id: number;
  vehicle_id: string;
  timestamp: string;
  code: string;
  detail: string;
}

interface ZoneCountsResponse {
  counts: Record<string, number>;
}

// --------------------------------------------------------------------------- //
// Helpers                                                                     //
// --------------------------------------------------------------------------- //

function formatClock(d: Date): string {
  return d.toTimeString().slice(0, 8); // "HH:MM:SS"
}

function formatTimestamp(ts: string | null): string {
  if (!ts) return '—';
  // Backend stores ISO-8601 UTC; toLocaleTimeString renders in local TZ.
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return formatClock(d);
}

const STATUS_DOT: Record<Status, string> = {
  idle: 'bg-green-500',
  moving: 'bg-blue-500',
  charging: 'bg-yellow-400',
  fault: 'bg-red-500',
};

// --------------------------------------------------------------------------- //
// <VehicleList /> — 50 rows with status dot, battery bar, recent anomaly     //
// --------------------------------------------------------------------------- //

function VehicleList({
  onTick,
  anomalies,
  anomaliesError,
}: {
  onTick: (when: Date) => void;
  anomalies: Anomaly[] | null;
  anomaliesError: string | null;
}) {
  const { data: vehicles, error: vehErr } = usePolledJson<Vehicle[]>(
    '/vehicles',
    onTick,
  );

  // Most-recent anomaly per vehicle, computed client-side from the descending
  // timestamp list — first occurrence wins.
  const latestByVehicle: Record<string, Anomaly> = {};
  if (anomalies) {
    for (const a of anomalies) {
      if (!(a.vehicle_id in latestByVehicle)) {
        latestByVehicle[a.vehicle_id] = a;
      }
    }
  }

  return (
    <section className="bg-white rounded shadow-sm border border-slate-200">
      <header className="px-4 py-3 border-b border-slate-200 flex items-center justify-between">
        <h2 className="text-base font-semibold text-slate-800">Vehicles</h2>
        <span className="text-xs text-slate-500">
          {vehicles ? `${vehicles.length} rows` : 'loading…'}
        </span>
      </header>
      {(vehErr || anomaliesError) && (
        <div className="px-4 py-2 text-sm text-red-700 bg-red-50 border-b border-red-200">
          {vehErr ?? anomaliesError}
        </div>
      )}
      <div className="overflow-x-auto max-h-[640px] overflow-y-auto">
        <table className="min-w-full text-sm">
          <thead className="sticky top-0 bg-slate-100 text-slate-600 text-xs uppercase tracking-wide">
            <tr>
              <th className="text-left px-4 py-2 font-medium">Vehicle</th>
              <th className="text-left px-4 py-2 font-medium">Status</th>
              <th className="text-left px-4 py-2 font-medium w-64">Battery</th>
              <th className="text-left px-4 py-2 font-medium">
                Latest anomaly
              </th>
            </tr>
          </thead>
          <tbody>
            {vehicles?.map((v) => {
              const battery = v.battery_pct ?? 0;
              const anomaly = latestByVehicle[v.vehicle_id];
              return (
                <tr
                  key={v.vehicle_id}
                  data-testid={`vehicle-row-${v.vehicle_id}`}
                  className="border-t border-slate-100 hover:bg-slate-50"
                >
                  <td className="px-4 py-2 font-mono text-slate-800">
                    {v.vehicle_id}
                  </td>
                  <td className="px-4 py-2">
                    <span className="inline-flex items-center gap-2">
                      <span
                        className={`inline-block w-2.5 h-2.5 rounded-full ${
                          STATUS_DOT[v.status] ?? 'bg-slate-400'
                        }`}
                        aria-label={v.status}
                      />
                      <span
                        data-testid={`vehicle-status-${v.vehicle_id}`}
                        className="text-slate-700"
                      >
                        {v.status}
                      </span>
                    </span>
                  </td>
                  <td className="px-4 py-2">
                    <div className="flex items-center gap-2">
                      <div className="flex-1 h-2 bg-slate-200 rounded overflow-hidden">
                        <div
                          className={`h-full ${
                            battery < 20
                              ? 'bg-red-500'
                              : battery < 40
                                ? 'bg-yellow-400'
                                : 'bg-green-500'
                          }`}
                          style={{
                            width: `${Math.max(0, Math.min(100, battery))}%`,
                          }}
                        />
                      </div>
                      <span className="tabular-nums text-slate-700 w-12 text-right">
                        {battery.toFixed(0)}%
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-2 text-slate-700">
                    {anomaly ? (
                      <span className="inline-flex items-center gap-2">
                        <span className="font-mono text-xs px-1.5 py-0.5 bg-amber-100 text-amber-800 rounded">
                          {anomaly.code}
                        </span>
                        <span className="text-xs text-slate-500">
                          {formatTimestamp(anomaly.timestamp)}
                        </span>
                      </span>
                    ) : (
                      <span className="text-slate-400">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// --------------------------------------------------------------------------- //
// <ZoneCounts /> — 20 cards, highlighted on change                            //
// --------------------------------------------------------------------------- //

function ZoneCounts({ onTick }: { onTick: (when: Date) => void }) {
  const { data, error } = usePolledJson<ZoneCountsResponse>(
    '/zones/counts',
    onTick,
  );

  // Highlight cards whose count changed on the latest poll. We diff inside
  // the effect (ref read/write outside render — satisfies react-hooks/refs)
  // and stash the result in `changed` state, which persists until the next
  // poll either resets or refreshes it.
  const counts = data?.counts ?? {};
  const prevRef = useRef<Record<string, number>>({});
  const [changed, setChanged] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!data) return;
    const next = new Set<string>();
    for (const [zone, value] of Object.entries(data.counts)) {
      const prior = prevRef.current[zone];
      if (prior !== undefined && prior !== value) {
        next.add(zone);
      }
    }
    prevRef.current = { ...data.counts };
    // `next` is derived from a cross-render diff (data vs. prevRef), which is
    // not expressible as pure render-time state — hence the suppressed rule.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setChanged(next);
  }, [data]);

  // Sorted zone IDs for stable layout.
  const zones = Object.keys(counts).sort();

  return (
    <section className="bg-white rounded shadow-sm border border-slate-200">
      <header className="px-4 py-3 border-b border-slate-200 flex items-center justify-between">
        <h2 className="text-base font-semibold text-slate-800">Zone entries</h2>
        <span className="text-xs text-slate-500">
          {zones.length ? `${zones.length} zones` : 'loading…'}
        </span>
      </header>
      {error && (
        <div className="px-4 py-2 text-sm text-red-700 bg-red-50 border-b border-red-200">
          {error}
        </div>
      )}
      <div className="p-3 grid grid-cols-2 md:grid-cols-4 gap-2">
        {zones.map((z) => (
          <div
            key={z}
            data-testid={`zone-card-${z}`}
            className={`border rounded px-3 py-2 transition-colors ${
              changed.has(z)
                ? 'border-blue-400 bg-blue-50'
                : 'border-slate-200 bg-slate-50'
            }`}
          >
            <div className="text-xs text-slate-500 font-mono truncate">{z}</div>
            <div
              data-testid={`zone-count-${z}`}
              className="text-xl font-semibold tabular-nums text-slate-800"
            >
              {counts[z]}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

// --------------------------------------------------------------------------- //
// <AnomalyFeed /> — 20 most recent anomalies                                  //
// --------------------------------------------------------------------------- //

function AnomalyFeed({
  anomalies,
  error,
}: {
  anomalies: Anomaly[] | null;
  error: string | null;
}) {
  // Render at most 20 rows — the parent feeds us the full 200-row poll so
  // we don't duplicate the /anomalies request.
  const data = anomalies ? anomalies.slice(0, 20) : null;

  return (
    <section className="bg-white rounded shadow-sm border border-slate-200">
      <header className="px-4 py-3 border-b border-slate-200 flex items-center justify-between">
        <h2 className="text-base font-semibold text-slate-800">
          Recent anomalies
        </h2>
        <span className="text-xs text-slate-500">
          {data ? `${data.length} rows` : 'loading…'}
        </span>
      </header>
      {error && (
        <div className="px-4 py-2 text-sm text-red-700 bg-red-50 border-b border-red-200">
          {error}
        </div>
      )}
      <ul className="divide-y divide-slate-100 max-h-[640px] overflow-y-auto">
        {data?.length === 0 && (
          <li className="px-4 py-6 text-sm text-slate-500 text-center">
            No anomalies in the last hour.
          </li>
        )}
        {data?.map((a) => (
          <li
            key={a.id}
            className="px-4 py-2 flex items-start gap-3 text-sm hover:bg-slate-50"
          >
            <span className="font-mono text-xs text-slate-500 mt-0.5">
              {formatTimestamp(a.timestamp)}
            </span>
            <span className="font-mono text-xs text-slate-700 mt-0.5">
              {a.vehicle_id}
            </span>
            <span className="font-mono text-xs px-1.5 py-0.5 bg-amber-100 text-amber-800 rounded">
              {a.code}
            </span>
            <span className="text-slate-600 text-xs flex-1 truncate">
              {a.detail}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

// --------------------------------------------------------------------------- //
// <App /> — top-level layout                                                  //
// --------------------------------------------------------------------------- //

function App() {
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  // Single anomalies poll for both the per-vehicle latest badge and the
  // recent-events feed (F-007). 200 is large enough to give VehicleList a
  // reliable most-recent-per-vehicle lookup; AnomalyFeed renders the top 20.
  const { data: anomalies, error: anomaliesError } = usePolledJson<Anomaly[]>(
    '/anomalies?limit=200',
    setLastUpdated,
  );

  return (
    <div className="min-h-screen bg-slate-100 text-slate-900">
      <header className="bg-white border-b border-slate-200">
        <div className="max-w-7xl mx-auto px-4 py-4 flex flex-wrap items-baseline justify-between gap-2">
          <h1 className="text-xl font-semibold">Fleet Telemetry Dashboard</h1>
          <div className="text-xs text-slate-500 flex flex-wrap items-center gap-x-4 gap-y-1">
            <span>
              API:{' '}
              <code className="font-mono text-slate-700">{API_BASE}</code>
            </span>
            <span>
              Last update:{' '}
              <span
                data-testid="last-updated"
                className="font-mono tabular-nums text-slate-700"
              >
                {lastUpdated ? formatClock(lastUpdated) : '—'}
              </span>
            </span>
            <span>
              Poll: <span className="font-mono">{POLL_MS} ms</span>
            </span>
          </div>
        </div>
      </header>
      <main className="max-w-7xl mx-auto p-4 grid gap-4 md:grid-cols-2">
        <div className="md:col-span-2">
          <VehicleList
            onTick={setLastUpdated}
            anomalies={anomalies}
            anomaliesError={anomaliesError}
          />
        </div>
        <ZoneCounts onTick={setLastUpdated} />
        <AnomalyFeed anomalies={anomalies} error={anomaliesError} />
      </main>
    </div>
  );
}

export default App;
