'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { createClient } from '@/lib/supabase';
import { Button } from '@/components/ui/button';
import { Plus, Trash2, Star } from 'lucide-react';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'https://integrated-os.vercel.app';

async function apiPost(path: string, body: any) {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${session?.access_token}`,
    },
    body: JSON.stringify(body),
  });
  return res.json();
}

async function apiGet(path: string) {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Authorization': `Bearer ${session?.access_token}` },
  });
  return res.json();
}

interface Domain {
  tag: string;
  name: string;
  description: string;
  context: string;
  icon: string;
  is_default?: boolean;
  parent_project_name?: string;
}

const DEFAULT_ICONS = ['💼', '🏠', '🚀', '🎨', '📋', '⚙️', '📚', '🎯'];

export default function OnboardingPage() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [ownerName, setOwnerName] = useState('');
  const [companyName, setCompanyName] = useState('');
  const [location, setLocation] = useState('');
  const [telegramCode, setTelegramCode] = useState('');
  const [telegramStatus, setTelegramStatus] = useState<'idle' | 'loading' | 'linked' | 'skipped'>('idle');
  const [domains, setDomains] = useState<Domain[]>([]);

  useEffect(() => {
    const supabase = createClient();
    supabase.auth.getUser().then(({ data: { user } }) => {
      if (!user) {
        router.push('/login');
        return;
      }
      apiGet('/api/auth/status').then((status) => {
        if (status.onboarding_completed) {
          router.push('/dashboard/tasks');
        }
        if (status.owner_name) setOwnerName(status.owner_name);
        if (status.company_name) setCompanyName(status.company_name);
        if (status.location && status.location !== 'India') setLocation(status.location);
      });
      apiGet('/api/onboarding/domains').then((res) => {
        setDomains(res.domains_config || []);
      });
    });
  }, [router]);

  const savePersona = async () => {
    await apiPost('/api/onboarding/persona', {
      owner_name: ownerName,
      company_name: companyName || undefined,
      location: location || undefined,
    });
    setStep(1);
  };

  const linkTelegram = async () => {
    setTelegramStatus('loading');
    const res = await apiPost('/api/onboarding/telegram/link', {});
    setTelegramCode(res.code);
    setTelegramStatus('idle');
  };

  const saveDomains = async () => {
    await apiPost('/api/onboarding/domains', { domains_config: domains });
    setStep(3);
  };

  const addDomain = () => {
    const tag = `DOMAIN${domains.length + 1}`;
    setDomains([...domains, {
      tag,
      name: '',
      description: '',
      context: 'work',
      icon: DEFAULT_ICONS[domains.length % DEFAULT_ICONS.length],
    }]);
  };

  const removeDomain = (index: number) => {
    const updated = domains.filter((_, i) => i !== index);
    if (updated.length > 0 && !updated.some(d => d.is_default)) {
      updated[0].is_default = true;
    }
    setDomains(updated);
  };

  const updateDomain = (index: number, field: keyof Domain, value: any) => {
    const updated = [...domains];
    (updated[index] as any)[field] = value;
    setDomains(updated);
  };

  const setDefault = (index: number) => {
    const updated = domains.map((d, i) => ({ ...d, is_default: i === index }));
    setDomains(updated);
  };

  const completeOnboarding = async () => {
    await apiPost('/api/onboarding/complete', {});
    router.push('/dashboard/tasks');
  };

  const totalSteps = 4;

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-gray-950 to-gray-900">
      <div className="w-full max-w-lg px-6">
        <div className="rounded-2xl border bg-gray-900/50 p-8 shadow-2xl backdrop-blur-xl">
          <div className="mb-8 flex items-center gap-2">
            {Array.from({ length: totalSteps }).map((_, s) => (
              <div key={s} className={`h-2 flex-1 rounded-full ${s <= step ? 'bg-primary' : 'bg-gray-700'}`} />
            ))}
          </div>

          {step === 0 && (
            <div>
              <h2 className="mb-6 text-xl font-bold text-white">Tell us about yourself</h2>
              <div className="space-y-4">
                <div>
                  <label className="mb-1 block text-sm text-gray-400">Your name *</label>
                  <input
                    value={ownerName}
                    onChange={(e) => setOwnerName(e.target.value)}
                    className="w-full rounded-lg border bg-gray-800 px-3 py-2 text-white"
                    placeholder="Your name"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-sm text-gray-400">Company (optional)</label>
                  <input
                    value={companyName}
                    onChange={(e) => setCompanyName(e.target.value)}
                    className="w-full rounded-lg border bg-gray-800 px-3 py-2 text-white"
                    placeholder="Your company"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-sm text-gray-400">Location (optional)</label>
                  <input
                    value={location}
                    onChange={(e) => setLocation(e.target.value)}
                    className="w-full rounded-lg border bg-gray-800 px-3 py-2 text-white"
                    placeholder="City, Country"
                  />
                </div>
                <Button onClick={savePersona} disabled={!ownerName.trim()} className="w-full mt-4">
                  Continue
                </Button>
              </div>
            </div>
          )}

          {step === 1 && (
            <div>
              <h2 className="mb-6 text-xl font-bold text-white">Link Telegram</h2>
              <p className="mb-4 text-sm text-gray-400">
                Link your Telegram account to send tasks and notes via chat.
              </p>
              {telegramCode ? (
                <div className="space-y-4">
                  <div className="rounded-lg border border-primary/30 bg-primary/5 p-4 text-center">
                    <p className="mb-1 text-xs text-gray-500">Send this code to the Rhodey bot on Telegram:</p>
                    <p className="text-2xl font-mono font-bold text-primary">{telegramCode}</p>
                  </div>
                  <p className="text-xs text-gray-500">Code expires in 10 minutes.</p>
                  <Button onClick={linkTelegram} variant="outline" className="w-full">
                    Generate new code
                  </Button>
                  <Button onClick={() => setStep(2)} className="w-full">
                    I sent the code — Continue
                  </Button>
                </div>
              ) : (
                <div className="space-y-4">
                  <Button onClick={linkTelegram} disabled={telegramStatus === 'loading'} className="w-full">
                    {telegramStatus === 'loading' ? 'Generating...' : 'Generate linking code'}
                  </Button>
                  <Button onClick={() => setStep(2)} variant="ghost" className="w-full text-gray-500">
                    Skip for now
                  </Button>
                </div>
              )}
            </div>
          )}

          {step === 2 && (
            <div>
              <div className="mb-6 flex items-center justify-between">
                <h2 className="text-xl font-bold text-white">Configure Domains</h2>
                <Button onClick={addDomain} size="sm" variant="outline" className="flex items-center gap-1">
                  <Plus className="h-4 w-4" /> Add
                </Button>
              </div>
              <p className="mb-4 text-sm text-gray-400">
                Domains are categories for your tasks and notes. The AI routes your messages into these domains.
              </p>
              <div className="space-y-3 max-h-80 overflow-y-auto pr-1">
                {domains.map((domain, i) => (
                  <div key={i} className="rounded-lg border bg-gray-800/50 p-3">
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <span className="text-lg">{domain.icon || '📁'}</span>
                        <span className="font-mono text-xs text-gray-500">{domain.tag}</span>
                        {domain.is_default && (
                          <span className="text-xs text-primary bg-primary/10 px-1.5 py-0.5 rounded">default</span>
                        )}
                      </div>
                      <div className="flex items-center gap-1">
                        {!domain.is_default && domains.length > 1 && (
                          <button onClick={() => setDefault(i)} className="p-1 text-gray-500 hover:text-amber-400" title="Set as default">
                            <Star className="h-3.5 w-3.5" />
                          </button>
                        )}
                        {domains.length > 1 && (
                          <button onClick={() => removeDomain(i)} className="p-1 text-gray-500 hover:text-red-400">
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        )}
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <input
                        value={domain.name}
                        onChange={(e) => updateDomain(i, 'name', e.target.value)}
                        className="rounded border bg-gray-900 px-2 py-1 text-sm text-white"
                        placeholder="Display name"
                      />
                      <input
                        value={domain.tag}
                        onChange={(e) => updateDomain(i, 'tag', e.target.value.toUpperCase())}
                        className="rounded border bg-gray-900 px-2 py-1 text-sm font-mono text-white"
                        placeholder="TAG"
                      />
                    </div>
                    <input
                      value={domain.description}
                      onChange={(e) => updateDomain(i, 'description', e.target.value)}
                      className="mt-2 w-full rounded border bg-gray-900 px-2 py-1 text-sm text-white"
                      placeholder="Description for AI routing"
                    />
                    <div className="mt-2 flex items-center gap-2">
                      <input
                        value={domain.icon}
                        onChange={(e) => updateDomain(i, 'icon', e.target.value)}
                        className="w-10 rounded border bg-gray-900 px-1 py-1 text-center text-sm"
                        placeholder="📁"
                      />
                      <select
                        value={domain.context}
                        onChange={(e) => updateDomain(i, 'context', e.target.value)}
                        className="rounded border bg-gray-900 px-2 py-1 text-sm text-white"
                      >
                        <option value="work">Work</option>
                        <option value="personal">Personal</option>
                      </select>
                    </div>
                  </div>
                ))}
              </div>
              <div className="mt-6 space-y-2">
                <Button onClick={saveDomains} className="w-full">
                  Continue
                </Button>
                <Button onClick={() => setStep(3)} variant="ghost" className="w-full text-gray-500">
                  Use defaults
                </Button>
              </div>
            </div>
          )}

          {step === 3 && (
            <div className="text-center">
              <h2 className="mb-4 text-xl font-bold text-white">You're all set!</h2>
              <p className="mb-8 text-sm text-gray-400">
                Your Rhodey OS is ready. Start sending tasks and notes via Telegram or the dashboard.
              </p>
              <Button onClick={completeOnboarding} className="w-full">
                Go to Dashboard
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
