import { NextResponse } from 'next/server';
import { createServerClient } from '@supabase/ssr';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'https://rhodey-three.vercel.app';

export async function GET(request: Request) {
  const url = new URL(request.url);
  const code = url.searchParams.get('code');

  if (!code) {
    return NextResponse.redirect(new URL('/login?error=auth_failed', url.origin));
  }

  const response = NextResponse.redirect(new URL('/dashboard/tasks', url.origin));

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.headers.get('cookie')?.split(';').map((c) => {
            const [name, ...rest] = c.trim().split('=');
            return { name, value: rest.join('=') };
          }) ?? [];
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value, options }) =>
            response.cookies.set(name, value, options)
          );
        },
      },
    }
  );

  const { error: sessionError } = await supabase.auth.exchangeCodeForSession(code);
  if (sessionError) {
    return NextResponse.redirect(new URL('/login?error=auth_failed', url.origin));
  }

  const { data: { user }, error: userError } = await supabase.auth.getUser();
  if (userError || !user) {
    return NextResponse.redirect(new URL('/login?error=auth_failed', url.origin));
  }

  const session = await supabase.auth.getSession();
  const token = session.data.session?.access_token;

  try {
    const registerRes = await fetch(`${API_BASE}/api/auth/register`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify({ owner_name: user.email?.split('@')[0] || 'User' }),
    });

    if (registerRes.ok) {
      const data = await registerRes.json();
      if (data.approval_status === 'pending') {
        return NextResponse.redirect(new URL('/pending-approval', url.origin));
      }
      if (data.approval_status === 'approved') {
        const statusRes = await fetch(`${API_BASE}/api/auth/status`, {
          headers: { 'Authorization': `Bearer ${token}` },
        });
        if (statusRes.ok) {
          const status = await statusRes.json();
          if (!status.onboarding_completed) {
            return NextResponse.redirect(new URL('/onboarding', url.origin));
          }
        }
      }
    }
  } catch (e) {
    console.error('Registration call failed:', e);
  }

  return NextResponse.redirect(new URL('/dashboard/tasks', url.origin));
}
