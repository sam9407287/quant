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
    setUser(currentUser());
    setReady(true);
    const onChange = () => setUser(currentUser());
    window.addEventListener("gq-auth-changed", onChange);
    return () => window.removeEventListener("gq-auth-changed", onChange);
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
