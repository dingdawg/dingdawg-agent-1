//##LLM:FILE: PRODUCT=dingdawg-platform SYSTEM=claw ENTRY=yes PART_OF=src/app/api/v1/claw CONNECTS_TO=src/components/claw/ClawButton.tsx BACK_REF=yes
import { NextRequest, NextResponse } from 'next/server';

export async function POST(req: NextRequest) {
  const { token, userId } = (await req.json()) as { token?: string; userId?: string };
  if (!token || !token.startsWith('hmac_')) {
    return NextResponse.json({ ok: false, error: 'Invalid token' }, { status: 403 });
  }
  return NextResponse.json({
    ok: true,
    receipt: {
      approved_at: new Date().toISOString(),
      token: token.slice(0, 16) + '...',
      approved_by: userId ?? null,
    },
  });
}
