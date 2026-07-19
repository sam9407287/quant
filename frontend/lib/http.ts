// Shared token storage + auth headers for the API client modules.
// The Google ID token lives in sessionStorage: it survives reloads
// within the tab but not a browser restart, matching its ~1h lifetime.

const TOKEN_KEY = "gq_id_token";

export function getIdToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.sessionStorage.getItem(TOKEN_KEY);
}

export function setIdToken(token: string): void {
  window.sessionStorage.setItem(TOKEN_KEY, token);
  window.dispatchEvent(new Event("gq-auth-changed"));
}

export function clearIdToken(): void {
  window.sessionStorage.removeItem(TOKEN_KEY);
  window.dispatchEvent(new Event("gq-auth-changed"));
}

/** Headers for authenticated API calls; empty when signed out. */
export function authHeaders(): Record<string, string> {
  const token = getIdToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export interface TokenClaims {
  email: string;
  name?: string;
  picture?: string;
  exp: number; // unix seconds
}

/** Decode the JWT payload for DISPLAY only — verification is the
 * backend's job; the UI just needs a name and an expiry to show. */
export function decodeToken(token: string): TokenClaims | null {
  try {
    const payload = token.split(".")[1];
    const json = JSON.parse(
      atob(payload.replace(/-/g, "+").replace(/_/g, "/")),
    ) as TokenClaims;
    if (!json.email || !json.exp) return null;
    return json;
  } catch {
    return null;
  }
}
