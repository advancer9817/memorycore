const capitalize = (str: string) => {
    if (!str) return ''
    if (str.length <= 1) return str.toUpperCase()
    return str.toUpperCase()[0] + str.slice(1)
}

function formatDate(timestamp: number | string, locale: "en" | "zh" = "en") {
    const date = typeof timestamp === 'number'
        ? new Date(timestamp)
        : new Date(timestamp);
    // Format as relative time (e.g., "5 minutes ago", "2 hours ago", "3 days ago")
    const now = new Date();
    const diffInSeconds = Math.floor((now.getTime() - date.getTime()) / 1000);

    if (diffInSeconds < 60) {
      return locale === "zh" ? "刚刚" : 'Just Now';
    } else if (diffInSeconds < 3600) {
      const minutes = Math.floor(diffInSeconds / 60);
      return locale === "zh" ? `${minutes} 分钟前` : `${minutes} ${minutes === 1 ? 'minute' : 'minutes'} ago`;
    } else if (diffInSeconds < 86400) {
      const hours = Math.floor(diffInSeconds / 3600);
      return locale === "zh" ? `${hours} 小时前` : `${hours} ${hours === 1 ? 'hour' : 'hours'} ago`;
    } else {
      const days = Math.floor(diffInSeconds / 86400);
      return locale === "zh" ? `${days} 天前` : `${days} ${days === 1 ? 'day' : 'days'} ago`;
    }
  }

export { capitalize, formatDate }