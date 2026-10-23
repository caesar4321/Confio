// Equipos + Liga (server: teams/). The palette and limits mirror teams/rules.py.
export const TEAM_EMOJIS = ['⚽', '🚀', '🦁', '🐂', '🦅', '🔥', '💎', '🌎', '📈', '🌱', '⭐', '🏆', '🐺', '🦉', '⚡', '🎯'];
export const TEAM_COLORS = ['#34D399', '#10B981', '#3B82F6', '#8B5CF6', '#F59E0B', '#EF4444', '#EC4899', '#14B8A6', '#111827'];
export const TEAM_NAME_MIN = 3;
export const TEAM_NAME_MAX = 24;
export const TEAM_DESCRIPTION_MAX = 140;
export const TEAM_MAX_MEMBERS = 20;

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
