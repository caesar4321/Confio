/**
 * Date formatting utilities for the Confío app
 * All functions respect the device's local timezone settings
 */

// Month names in Spanish
const MONTH_NAMES_ES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];

/**
 * Format a date string to device's local time with full date and time
 * @param dateString - ISO date string or any valid date string
 * @returns Formatted string like "25 jul 2025, 3:45 PM"
 */
export const formatLocalDateTime = (dateString: string): string => {
  const date = new Date(dateString);
  
  // Check if date is valid
  if (isNaN(date.getTime())) {
    return 'Fecha inválida';
  }
  
  // The Date object automatically uses the device's timezone when parsing ISO strings
  // and converting to local time components
  
  // Format date parts using the device's local timezone
  const day = date.getDate().toString().padStart(2, '0');
  const month = MONTH_NAMES_ES[date.getMonth()];
  const year = date.getFullYear();
  
  // Get hours in device's local timezone
  let hours = date.getHours();
  const minutes = date.getMinutes().toString().padStart(2, '0');
  const ampm = hours >= 12 ? 'PM' : 'AM';
  hours = hours % 12;
  hours = hours ? hours : 12; // 0 should be 12
  
  return `${day} ${month} ${year}, ${hours}:${minutes} ${ampm}`;
};

/**
 * Format a date string to device's local date only
 * @param dateString - ISO date string or any valid date string
 * @returns Formatted string like "25 jul 2025"
 */
export const formatLocalDate = (dateString: string): string => {
  const date = new Date(dateString);
  
  // Check if date is valid
  if (isNaN(date.getTime())) {
    return 'Fecha inválida';
  }
  
  const day = date.getDate().toString().padStart(2, '0');
  const month = MONTH_NAMES_ES[date.getMonth()];
  const year = date.getFullYear();
  
  return `${day} ${month} ${year}`;
};

/**
 * Format a date string to device's local time only
 * @param dateString - ISO date string or any valid date string
 * @returns Formatted string like "3:45 PM"
 */
export const formatLocalTime = (dateString: string): string => {
  const date = new Date(dateString);
  
  // Check if date is valid
  if (isNaN(date.getTime())) {
    return 'Hora inválida';
  }
  
  let hours = date.getHours();
  const minutes = date.getMinutes().toString().padStart(2, '0');
  const ampm = hours >= 12 ? 'PM' : 'AM';
  hours = hours % 12;
  hours = hours ? hours : 12; // 0 should be 12
  
  return `${hours}:${minutes} ${ampm}`;
};

/**
 * Get the device's current timezone offset
 * @returns Timezone offset string like "GMT-5" or "GMT+1"
 */
export const getDeviceTimezone = (): string => {
  const date = new Date();
  const timeZoneOffset = -date.getTimezoneOffset() / 60;
  const timeZoneSign = timeZoneOffset >= 0 ? '+' : '';
  return `GMT${timeZoneSign}${timeZoneOffset}`;
};

/**
 * Format a date string with timezone info
 * @param dateString - ISO date string or any valid date string
 * @returns Formatted string like "25 jul 2025, 3:45 PM (GMT-5)"
 */
export const formatLocalDateTimeWithTimezone = (dateString: string): string => {
  const dateTime = formatLocalDateTime(dateString);
  const timezone = getDeviceTimezone();
  return `${dateTime} (${timezone})`;
};

/**
 * Calculate time ago from a date
 * @param dateString - ISO date string or any valid date string
 * @returns String like "hace 5 minutos", "hace 2 horas", "hace 3 días"
 */
export const getTimeAgo = (dateString: string): string => {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffSecs / 60);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);
  
  if (diffSecs < 60) {
    return 'hace un momento';
  } else if (diffMins < 60) {
    return `hace ${diffMins} ${diffMins === 1 ? 'minuto' : 'minutos'}`;
  } else if (diffHours < 24) {
    return `hace ${diffHours} ${diffHours === 1 ? 'hora' : 'horas'}`;
  } else if (diffDays < 30) {
    return `hace ${diffDays} ${diffDays === 1 ? 'día' : 'días'}`;
  } else {
    return formatLocalDate(dateString);
  }
};