using System;
using System.Net;
using Ironkeep;

namespace Ironkeep.Companion
{
    /// <summary>
    /// Guild-scoped bearer upload used until Discord login exists.
    /// The slug is the guild id stored with the snapshot. The key is read at send time and is not logged.
    /// </summary>
    public sealed class LegacyUploader : IReportUploader
    {
        readonly Func<CompanionConfig> _current;

        public LegacyUploader(Func<CompanionConfig> current)
        {
            if (current == null) throw new ArgumentNullException("current");
            _current = current;
        }

        public string LastResponse = "";
        public int LastStatus;

        public UploadResult Upload(string guildId, string body)
        {
            return Upload(guildId, body, "attendance");
        }

        public UploadResult Upload(string guildId, string body, string kind)
        {
            if (string.Equals(kind, RosterPayload.Kind, StringComparison.Ordinal))
                return Finish(403, "{\"ok\":false}");
            CompanionConfig config = _current() ?? new CompanionConfig();
            string token = config.Token ?? "";
            if (token.Length == 0)
                return Finish(401, "");
            string problem;
            Uri url = SiteClient.Target(config.Address, guildId, out problem);
            if (url == null)
                return Finish(400, "");
            try
            {
                int status;
                string response = SiteClient.Post(url, token, body, out status);
                return Finish(status, response ?? "");
            }
            catch (WebException)
            {
                LastResponse = "";
                LastStatus = 0;
                return new UploadResult { Status = 0, Body = "", TransportFailed = true };
            }
        }

        UploadResult Finish(int status, string body)
        {
            LastStatus = status;
            LastResponse = body ?? "";
            return new UploadResult { Status = status, Body = LastResponse };
        }
    }
}
