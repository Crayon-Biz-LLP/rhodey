import { createClient } from '@/lib/supabase';

export const fetcher = async (url: string) => {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  const headers: Record<string, string> = {};
  if (session?.access_token) {
    headers['Authorization'] = `Bearer ${session.access_token}`;
  }
  const res = await fetch(url, { headers });
  if (!res.ok) throw new Error(`Failed to fetch ${url}`);
  return res.json();
};

export const swrConfig = {
  dedupingInterval: 30000,
  revalidateOnFocus: false,
  revalidateOnReconnect: false,
  errorRetryCount: 2,
};
