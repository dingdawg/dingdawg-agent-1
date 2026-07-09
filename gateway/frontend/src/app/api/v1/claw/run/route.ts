//##LLM:FILE: PRODUCT=dingdawg-platform SYSTEM=claw ENTRY=yes PART_OF=src/app/api/v1/claw CONNECTS_TO=src/components/claw/ClawButton.tsx BACK_REF=yes
import { NextRequest } from 'next/server';
import { createHmac } from 'crypto';

interface ClawProposal {
  type: string;
  to: string;
  toName: string;
  subject: string;
  body: string;
  daysSilent: number;
}

export async function POST(req: NextRequest) {
  const { workflow, userId } = (await req.json()) as { workflow?: string; userId?: string };
  const encoder = new TextEncoder();

  const stream = new ReadableStream({
    async start(controller) {
      const send = (event: string, data: object) => {
        controller.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`));
      };
      try {
        send('thinking', { step: 'Initializing workflow...', ts: Date.now() });
        send('thinking', { step: `Running: ${workflow ?? 'unknown'}`, ts: Date.now() });

        // Placeholder proposals — replace with real DB query when wired to backend.
        const proposals: ClawProposal[] = [
          {
            type: 'email_proposal',
            to: 'demo@example.com',
            toName: 'Demo Contact',
            subject: 'Checking in',
            body: 'Hi there...',
            daysSilent: 32,
          },
        ];

        const secret = process.env.HMAC_SECRET || 'changeme';
        const token =
          'hmac_' +
          createHmac('sha256', secret).update(JSON.stringify(proposals)).digest('hex');

        send('proposal', {
          action: 'send_emails',
          proposals,
          token,
          expires_at: Date.now() + 300_000,
          requested_by: userId ?? null,
        });
        send('done', { status: 'awaiting_approval', count: proposals.length });
      } catch (e: unknown) {
        const message = e instanceof Error ? e.message : 'unknown_error';
        send('error', { message });
      } finally {
        controller.close();
      }
    },
  });

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
    },
  });
}
