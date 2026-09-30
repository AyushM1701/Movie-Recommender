export function safeStoredArray(value) {
  try { const parsed = JSON.parse(value || '[]'); return Array.isArray(parsed) ? [...new Set(parsed.filter(item => typeof item === 'string'))] : []; }
  catch { return []; }
}

export class RequestOwnership {
  constructor() { this.requests = new Map(); this.session = 0; }
  begin(key) {
    this.requests.get(key)?.controller.abort();
    const controller = new AbortController();
    const session = this.session;
    const record = {controller};
    this.requests.set(key, record);
    return {signal:controller.signal, isCurrent: () => this.session === session && this.requests.get(key) === record && !controller.signal.aborted};
  }
  cancel(key) { this.requests.get(key)?.controller.abort(); this.requests.delete(key); }
  resetSession() { this.session += 1; for (const key of this.requests.keys()) this.cancel(key); }
}

export function blendInputs(ids, genres, weight) {
  if (!Number.isFinite(weight) || weight < 0 || weight > 1) throw new Error('Choose a valid blend weight.');
  const movie_ids = [...new Set(ids.filter(id => Number.isInteger(id) && id > 0))];
  genres = [...new Set(genres)];
  if (!movie_ids.length && !genres.length) throw new Error('Select at least one movie or genre to run a blend.');
  const weight_content = !movie_ids.length ? 0 : !genres.length ? 1 : weight;
  return {movie_ids, genres, weight_content, weight_genre:Number((1 - weight_content).toFixed(2))};
}

export function routeFromHash(hash) {
  const value = hash.replace(/^#\/?/, '');
  if (/^list\/[a-zA-Z0-9_-]+$/.test(value)) return {page:'shared-list',slug:value.slice(5)};
  if (/^my-list\/\d+$/.test(value)) return {page:'owner-list',id:Number(value.slice(8))};
  return {page:['explore','for-you','genres','history','hybrid','library','profile','auth'].includes(value) ? value : 'explore'};
}
