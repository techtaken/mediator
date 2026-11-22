import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "Privacy · Mediator" };

// Shown as the way to reach us. Set NEXT_PUBLIC_CONTACT_EMAIL on Vercel.
const CONTACT = process.env.NEXT_PUBLIC_CONTACT_EMAIL;
const UPDATED = "22 November 2026";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-10">
      <h2 className="font-[family-name:var(--font-display)] text-2xl text-ink">{title}</h2>
      <div className="mt-3 space-y-3 text-[16px] leading-relaxed text-muted">{children}</div>
    </section>
  );
}

export default function PrivacyPage() {
  return (
    <main className="mx-auto w-full max-w-2xl px-5 py-10">
      <Link href="/" className="text-sm tracking-[0.2em] text-terracotta uppercase">
        Mediator
      </Link>
      <h1 className="mt-10 font-[family-name:var(--font-display)] text-4xl text-ink">Privacy and terms</h1>
      <p className="mt-3 text-sm text-muted">Last updated {UPDATED}</p>
      <p className="mt-6 text-[17px] leading-relaxed text-ink">
        Mediator helps two people work through a disagreement. Each of you talks privately with an AI mediator, and the
        other person only sees words you approve. This page explains what we keep, who can see it, and how to delete it.
      </p>

      <Section title="What we keep">
        <p>
          <strong className="text-ink">Your account:</strong> your email address (from Google or an email sign-in link)
          and the name you give us.
        </p>
        <p>
          <strong className="text-ink">Each conversation:</strong> its topic, both people&apos;s names, your private chat
          with the mediator, the mediator&apos;s private notes about your side, what you each chose to share, and the
          joint ideas and agreement.
        </p>
        <p>
          <strong className="text-ink">Invited person&apos;s PIN:</strong> stored only as a one-way hash, so nobody can
          read it back.
        </p>
      </Section>

      <Section title="Who can see what">
        <p>
          The other person never sees your private chat. They only see text you approved on the share screen, and the
          joint stage you both take part in.
        </p>
        <p>
          Private chats, the mediator&apos;s private notes and share text are stored encrypted. Our team&apos;s admin
          tools don&apos;t show private messages. Our server holds the key, because it has to read your messages to
          write the mediator&apos;s replies.
        </p>
        <p>
          To write replies, your messages are sent to Google&apos;s Gemini AI. While we use Google&apos;s free tier,
          Google may use that text to improve its products, and people at Google may review it. Please don&apos;t
          include details you wouldn&apos;t want anyone else to read, such as account numbers or addresses.
        </p>
        <p>We don&apos;t sell your data or use it for advertising.</p>
      </Section>

      <Section title="Services we use">
        <p>
          Supabase (database and sign-in), Google (sign-in and the Gemini AI), Render (our server) and Vercel (this
          website). They process data only to run Mediator.
        </p>
      </Section>

      <Section title="How long we keep it, and deleting it">
        <p>Conversations are removed automatically 180 days after they are opened.</p>
        <p>
          Inside a conversation you can delete your own data at any time. The person who opened a conversation can
          delete it entirely. To delete your account, contact us.
        </p>
      </Section>

      <Section title="What Mediator is not">
        <p>
          Mediator is an AI tool, not a therapist, lawyer or counsellor, and it doesn&apos;t give legal, medical or
          financial advice. It isn&apos;t for emergencies, violence or abuse. If you are in danger, call 112.
        </p>
        <p>
          Agreements made here aren&apos;t legally binding. By using Mediator you agree to use it honestly and not to
          harass or threaten anyone through it.
        </p>
      </Section>

      <Section title="Contact">
        <p>
          {CONTACT ? (
            <>
              Questions or deletion requests:{" "}
              <a href={`mailto:${CONTACT}`} className="text-teal underline underline-offset-4">
                {CONTACT}
              </a>
              .
            </>
          ) : (
            "Questions or deletion requests: write to the support email shown on the Google sign-in screen."
          )}
        </p>
      </Section>
    </main>
  );
}
