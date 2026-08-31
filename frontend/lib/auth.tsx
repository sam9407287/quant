"use client";

// Google Identity Services sign-in state. The GIS script issues an ID
// token; we keep it in sessionStorage (lib/http.ts) and re-derive the
// signed-in user from its claims. Expired tokens are dropped on load.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";

import {
  clearIdToken,
  decodeToken,
  devApiToken,
  getIdToken,
  setIdToken,
  type TokenClaims,
} from "@/lib/http";

export const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || "";

interface AuthState {
  user: TokenClaims | null;
  ready: boolean;
  signOut: () => void;
}

const Ctx = createContext<AuthState>({ user: null, ready: false, signOut: () => {} });

export function useAuth(): AuthState {
  return useContext(Ctx);
}

function currentUser(): TokenClaims | null {
  // A dev server started with a service token counts as signed in, or the
  // pages behind RequireAuth would still be unreachable. Never true in a
  // production build — devApiToken() returns null there.
  if (devApiToken()) {
    return { email: "service token", exp: Number.MAX_SAFE_INTEGER / 1000 };
  }
  const token = getIdToken();
  if (!token) return null;
  const claims = decodeToken(token);
  if (!claims || claims.exp * 1000 < Date.now()) {
    clearIdToken();
    return null;
  }
  return claims;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<TokenClaims | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setReady(true);
    let expiryTimer: ReturnType<typeof setTimeout> | undefined;

    // Proactively drop the token the moment it expires, so the UI flips
    // to signed-out (sign-in button returns, strategy dropdown disables)
    // BEFORE the user hits a 401 mid-action.
    const sync = () => {
      if (expiryTimer) clearTimeout(expiryTimer);
      const u = currentUser();
      setUser(u);
      if (u) {
        const msLeft = u.exp * 1000 - Date.now();
        expiryTimer = setTimeout(() => clearIdToken(), Math.max(0, msLeft));
      }
    };

    sync();
    window.addEventListener("gq-auth-changed", sync);
    return () => {
      window.removeEventListener("gq-auth-changed", sync);
      if (expiryTimer) clearTimeout(expiryTimer);
    };
  }, []);

  const signOut = useCallback(() => {
    clearIdToken();
  }, []);

  return <Ctx.Provider value={{ user, ready, signOut }}>{children}</Ctx.Provider>;
}

// Called by the GIS button callback (components/auth/sign-in.tsx).
export function handleCredential(credential: string): void {
  setIdToken(credential);
}
