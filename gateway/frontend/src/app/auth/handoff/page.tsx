'use client';

import { useEffect, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';

/**
 * Cross-origin token handoff page.
 *
 * dingdawg.com stores auth tokens in its own localStorage (inaccessible from
 * app.dingdawg.com due to same-origin policy). After login/register on
 * dingdawg.com the user lands here:
 *   https://app.dingdawg.com/auth/handoff?t=<jwt>&u=<user_id>&e=<email>
 *
 * Stores the token in this origin's localStorage then forwards to /dashboard.
 * Falls back to /login if no token present.
 */
function HandoffInner() {
  const router = useRouter();
  const params = useSearchParams();

  useEffect(() => {
    const token = params.get('t');
    const userId = params.get('u');
    const email = params.get('e');
    const welcome = params.get('welcome');

    if (!token) {
      router.replace('/login');
      return;
    }

    localStorage.setItem('dd_token', token);
    if (userId) localStorage.setItem('dd_user_id', userId);
    if (email) localStorage.setItem('dd_email', email);

    router.replace(welcome === '1' ? '/dashboard?welcome=1' : '/dashboard');
  }, [router, params]);

  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center bg-[#06101d]">
      <div className="inline-block h-8 w-8 animate-spin rounded-full border-2 border-[#d6a43a] border-t-transparent" />
    </div>
  );
}

export default function HandoffPage() {
  return (
    <Suspense
      fallback={
        <div className="fixed inset-0 z-[200] flex items-center justify-center bg-[#06101d]">
          <div className="inline-block h-8 w-8 animate-spin rounded-full border-2 border-[#d6a43a] border-t-transparent" />
        </div>
      }
    >
      <HandoffInner />
    </Suspense>
  );
}
