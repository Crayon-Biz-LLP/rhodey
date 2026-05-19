'use client';

import { Clock } from 'lucide-react';
import { createClient } from '@/lib/supabase';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';

export default function PendingApprovalPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');

  useEffect(() => {
    const supabase = createClient();
    supabase.auth.getUser().then(({ data: { user } }) => {
      if (!user) {
        router.push('/login');
      } else {
        setEmail(user.email || '');
      }
    });
  }, [router]);

  const handleSignOut = async () => {
    const supabase = createClient();
    await supabase.auth.signOut();
    router.push('/login');
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-gray-950 to-gray-900">
      <div className="w-full max-w-md px-6">
        <div className="rounded-2xl border bg-gray-900/50 p-8 shadow-2xl backdrop-blur-xl text-center">
          <div className="mx-auto mb-6 flex h-16 w-16 items-center justify-center rounded-full bg-amber-500/10">
            <Clock className="h-8 w-8 text-amber-400" />
          </div>
          <h1 className="mb-2 text-2xl font-bold text-white">Pending Approval</h1>
          <p className="mb-2 text-sm text-gray-400">
            Your account ({email}) is awaiting admin approval.
          </p>
          <p className="mb-8 text-sm text-gray-500">
            You will be notified once access is granted.
          </p>
          <button
            onClick={handleSignOut}
            className="text-sm text-gray-500 hover:text-gray-300 underline"
          >
            Sign out
          </button>
        </div>
      </div>
    </div>
  );
}
