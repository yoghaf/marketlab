"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

export function AutoRefresh({ intervalSeconds = 60 }: { intervalSeconds?: number }) {
  const router = useRouter();
  const effectiveIntervalSeconds = Math.max(intervalSeconds, 60);

  useEffect(() => {
    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") router.refresh();
    };
    const timer = window.setInterval(refreshWhenVisible, effectiveIntervalSeconds * 1000);
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
    };
  }, [effectiveIntervalSeconds, router]);

  return null;
}
