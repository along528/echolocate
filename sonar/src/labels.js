/**
 * Search-event + label logging (training signal). Slim port of the legacy
 * frontend Labels module. Fire-and-forget; never blocks the UI.
 */
import { API } from './api.js';

function uuid() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

export const Labels = {
  sessionId: null,
  versions: null,
  disabled: false,

  init() {
    this.disabled = localStorage.getItem('echolocate-labels-disabled') === '1';
    let sid = localStorage.getItem('echolocate-session-id');
    if (!sid) {
      sid = uuid();
      localStorage.setItem('echolocate-session-id', sid);
    }
    this.sessionId = sid;
    API.getVersion().then((v) => { this.versions = v; }).catch(() => {});
  },

  _newId() {
    return `${Date.now()}-${uuid()}`;
  },

  /** Record a search; stamps each track with _searchId + _rank for later labels. */
  recordSearch(endpoint, queryKind, queryFields, params, tracks) {
    if (this.disabled || !Array.isArray(tracks)) return null;
    const searchId = this._newId();
    tracks.forEach((t, i) => {
      if (t && typeof t === 'object') {
        t._searchId = searchId;
        t._rank = i;
      }
    });
    API.logSearchEvent({
      search_id: searchId,
      session_id: this.sessionId,
      endpoint,
      query_kind: queryKind,
      query: queryFields || {},
      params: params || {},
      results: tracks.filter((t) => t && t.id).map((t, i) => ({ id: t.id, rank: i })),
      client_versions: this.versions || null,
    });
    return searchId;
  },

  recordLabel(track, signal, note) {
    if (this.disabled || !track || !track._searchId || !track.id) return;
    API.logLabelEvent({
      label_id: this._newId(),
      search_id: track._searchId,
      session_id: this.sessionId,
      track_id: track.id,
      rank: typeof track._rank === 'number' ? track._rank : -1,
      signal,
      note: note || null,
    });
  },
};
