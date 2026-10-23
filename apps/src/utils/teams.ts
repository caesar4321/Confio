// Teams and the league (server: teams/). The palette and limits mirror teams/rules.py.
export const TEAM_EMOJIS = ['⚽', '🚀', '🦁', '🐂', '🦅', '🔥', '💎', '🌎', '📈', '🌱', '⭐', '🏆', '🐺', '🦉', '⚡', '🎯'];
export const TEAM_COLORS = ['#34D399', '#10B981', '#3B82F6', '#8B5CF6', '#F59E0B', '#EF4444', '#EC4899', '#14B8A6', '#111827'];
export const TEAM_NAME_MIN = 3;
export const TEAM_NAME_MAX = 24;
export const TEAM_DESCRIPTION_MAX = 140;
export const TEAM_MAX_MEMBERS = 20;
// A team ranks in the league from this many members with history (teams/league.py).
export const TEAM_MIN_RANKED = 5;

export const LEAGUE_RANGES = [
  { key: '24h', label: '24 h' },
  { key: '7d', label: '7 d' },
  { key: '30d', label: '30 d' },
  { key: 'month', label: 'Mes' },
] as const;
export type LeagueRange = (typeof LEAGUE_RANGES)[number]['key'];

const MONTHS = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre',
  'noviembre', 'diciembre'];

/** "2026-10" → "Campeón de octubre 2026". */
export const championLabel = (month: string): string => {
  const match = /^(\d{4})-(\d{2})$/.exec(month || '');
  if (!match) return '';
  const index = Number(match[2]) - 1;
  return index >= 0 && index < 12 ? `Campeón de ${MONTHS[index]} ${match[1]}` : '';
};

/** "🥇" / "🥈" / "🥉" for the podium, else "4." */
export const rankMark = (rank: number): string => (rank === 1 ? '🥇' : rank === 2 ? '🥈' : rank === 3 ? '🥉' : `${rank}.`);

/** BuyStock takes the underlying ticker ("NVDA"); the GM symbol is "NVDAon". */
export const tickerOfSymbol = (symbol: string): string => symbol.replace(/on$/, '');

export type LeagueRow = {
  rank: number;
  pct: string;
  members?: number | null;
  userId?: string | null;
  username?: string | null;
  avatarUrl?: string | null;
  team?: { id: string; name: string; emoji: string; color: string; memberCount: number } | null;
};

export type TeamGoal = {
  kind: 'invested_usd' | 'weekly_investors' | string;
  target: string;
  progress: string;
  percent: number;
  deadline?: string | null;
  reached: boolean;
};

export type Team = {
  id: string;
  name: string;
  description: string;
  emoji: string;
  color: string;
  joinMode: 'open' | 'approval' | string;
  country?: string | null;
  memberCount: number;
  captainId: string;
  isMember: boolean;
  isCaptain: boolean;
  isFollowing: boolean;
  joinRequest?: string | null;
  joinBlock?: string | null;
  joinBlockMessage?: string | null;
  access: 'open' | 'viewer_hidden' | 'viewer_unverified' | string;
  returnPct?: string | null;
  leagueRank?: number | null;
  championMonths: string[];
  pendingRequests?: number | null;
  goal?: TeamGoal | null;
};

/** "Invertir juntos $1,000" / "3 miembros invirtiendo esta semana". */
export const goalLabel = (goal: TeamGoal): string => {
  if (goal.kind === 'invested_usd') return `Invertir juntos $${Number(goal.target).toLocaleString('en-US')}`;
  const n = Number(goal.target);
  return `${n} ${n === 1 ? 'miembro invirtiendo' : 'miembros invirtiendo'} esta semana`;
};

/**
 * The team link rides the invite path (/invite/{code}, an app link on both
 * platforms, and the code survives a store install as the referrer) with a
 * code no username can take: "team~{token}". It never carries the inviter's
 * username.
 */
export const buildTeamInviteLink = (token: string): string =>
  `https://confio.lat/invite/team~${encodeURIComponent(token)}?source=team`;

export const buildTeamInviteMessage = (teamName: string, link: string): string =>
  `Únete a mi equipo "${teamName}" en Confío. Invertimos cada uno desde su cuenta y competimos en la Liga por rentabilidad.\n\n${link}`;

/** The team token in an invite/referral code ("team~…", any case), or null. */
export const teamTokenFromCode = (code: string | null | undefined): string | null => {
  const match = /^team~([a-z0-9]{12,32})$/i.exec(String(code || '').trim());
  return match ? match[1].toLowerCase() : null;
};
