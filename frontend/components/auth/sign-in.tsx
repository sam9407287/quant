"use client";

// Google Identity Services button + signed-in chip. Client island so
// the surrounding Nav can stay a server component.

import Image from "next/image";
import Script from "next/script";
import { useCallback, useEffect, useRef, useState } from "react";

import { GOOGLE_CLIENT_ID, handleCredential, useAuth } from "@/lib/auth";

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (cfg: {
            client_id: string;
            callback: (resp: { credential: string }) => void;
          }) => void;
          renderButton: (el: HTMLElement, cfg: Record<string, unknown>) => void;
          disableAutoSelect: () => void;
        };
      };
    };
  }
}

export function AuthButton() {
  const { user, ready, signOut } = useAuth();
  const buttonRef = useRef<HTMLDivElement | null>(null);
  const [gisLoaded, setGisLoaded] = useState(false);

  const renderGoogleButton = useCallback(() => {
    if (!window.google || !buttonRef.current || !GOOGLE_CLIENT_ID) return;
    window.google.accounts.id.initialize({
      client_id: GOOGLE_CLIENT_ID,
      callback: (resp) => handleCredential(resp.credential),
    });
    buttonRef.current.innerHTML = "";
    window.google.accounts.id.renderButton(buttonRef.current, {
      theme: "filled_black",
      size: "medium",
      shape: "pill",
      text: "signin_with",
    });
  }, []);

  useEffect(() => {
    if (gisLoaded && !user) renderGoogleButton();
  }, [gisLoaded, user, renderGoogleButton]);

  if (!GOOGLE_CLIENT_ID) return null; // auth not configured — hide entirely

  if (user) {
    return (
      <div className="flex items-center gap-2">
        {user.picture && (
          <Image
            src={user.picture}
            alt=""
            width={24}
            height={24}
            unoptimized
            className="rounded-full"
          />
        )}
        <span className="hidden font-mono text-xs text-zinc-400 sm:inline">
          {user.email}
        </span>
        <button
          type="button"
          onClick={() => {
            window.google?.accounts.id.disableAutoSelect();
            signOut();
          }}
          className="rounded-md bg-bg-hover px-3 py-1.5 font-mono text-xs uppercase tracking-wider text-zinc-400 transition hover:text-zinc-100"
        >
          Sign out
        </button>
      </div>
    );
  }

  return (
    <>
      <Script
        src="https://accounts.google.com/gsi/client"
        strategy="afterInteractive"
        onLoad={() => setGisLoaded(true)}
      />
      {/* Placeholder keeps layout stable until GIS renders into it. */}
      <div ref={buttonRef} className={ready ? "" : "invisible"} />
    </>
  );
}
