using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using Ironkeep;

namespace Ironkeep.Companion
{
    public interface IBrowser
    {
        void Open(string url);
    }

    public sealed class SystemBrowser : IBrowser
    {
        public void Open(string url)
        {
            System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(url) { UseShellExecute = true });
        }
    }

    public sealed class TokenReply
    {
        public int Status;
        public bool TransportFailed;
        public string Access = "";
        public string Refresh = "";
        public int ExpiresIn;
        public string Body = "";
    }

    /// <summary>
    /// Browser approval, code exchange, refresh, guild discovery, and logout.
    /// Tokens are returned to the caller. This type does not write logs.
    /// </summary>
    public sealed class DiscordLogin
    {
        readonly Func<CompanionConfig> _read;
        readonly Action<CompanionConfig> _write;
        readonly Action<List<CompanionGuild>> _remember;
        readonly IBrowser _browser;
        readonly object _refreshGate = new object();

        public TimeSpan Timeout = TimeSpan.FromSeconds(600);
        public Func<DateTime> Clock = delegate { return DateTime.UtcNow; };
        internal string VerifierOverride = "";
        internal string ChallengeOverride = "";

        public DiscordLogin(Func<CompanionConfig> read, Action<CompanionConfig> write, Action<List<CompanionGuild>> remember, IBrowser browser)
        {
            if (read == null) throw new ArgumentNullException("read");
            if (write == null) throw new ArgumentNullException("write");
            if (browser == null) throw new ArgumentNullException("browser");
            _read = read;
            _write = write;
            _remember = remember ?? delegate { };
            _browser = browser;
        }

        public LoginResult Run(CancellationToken cancel, Action<CompanionAuthState> progress)
        {
            if (progress == null) progress = delegate { };
            progress(CompanionAuthState.Connecting);
            LoopbackBroker broker = null;
            try
            {
                broker = LoopbackBroker.Start();
                string state = CompanionProtocol.RandomSecret(32);
                string verifier = VerifierOverride != null && VerifierOverride.Length > 0 ? VerifierOverride : CompanionProtocol.RandomSecret(64);
                string challenge = ChallengeOverride != null && ChallengeOverride.Length > 0 ? ChallengeOverride : CompanionProtocol.ChallengeS256(verifier);
                CompanionConfig config = _read() ?? new CompanionConfig();
                string redirect = broker.RedirectUri;
                string url = CompanionProtocol.ConnectUrl(config.Address, redirect, state, challenge);
                progress(CompanionAuthState.AwaitingApproval);
                try
                {
                    _browser.Open(url);
                }
                catch (Exception)
                {
                    return Fail("The browser could not be opened.");
                }
                LoopbackHit hit = broker.Wait(Timeout, cancel);
                if (hit.Kind == "timeout") return Fail("The browser did not finish the connection in time.");
                if (hit.Kind != "callback") return new LoginResult { Kind = "cancelled", Detail = "" };
                if (string.Equals(hit.Error, "access_denied", StringComparison.Ordinal))
                    return Fail("rejected", "The connection was refused in the browser.");
                if (hit.Error != null && hit.Error.Length > 0)
                    return Fail("The connection was refused in the browser.");
                if (!CompanionProtocol.FixedEqual(state, hit.State))
                    return Fail("invalid-state", "The browser returned a different connection check.");
                if (cancel.IsCancellationRequested) return new LoginResult { Kind = "cancelled", Detail = "" };
                TokenReply exchanged = PostToken(config.Address, AuthorizationBody(hit.Code, verifier, redirect), "");
                if (exchanged.TransportFailed) return Fail("Ironkeep could not be reached.");
                if (exchanged.Status == 404) return Fail("Companion login is not enabled on this site.");
                if (exchanged.Status != 200 || !exchanged.Access.StartsWith(CompanionProtocol.AccessPrefix, StringComparison.Ordinal) || !exchanged.Refresh.StartsWith(CompanionProtocol.RefreshPrefix, StringComparison.Ordinal))
                    return Fail("The authorization code was rejected.");
                return StoreAndDiscover(config, exchanged, true);
            }
            catch (Exception)
            {
                return Fail("The connection did not complete.");
            }
            finally
            {
                if (broker != null) broker.Dispose();
            }
        }

        public LoginResult RefreshGuilds()
        {
            bool transport;
            string access = EnsureAccess(false, out transport);
            if (transport) return Fail("Ironkeep could not be reached.");
            if (access == null || access.Length == 0)
                return new LoginResult { Kind = "expired", Detail = "Sign in with Discord again. The legacy key is not used." };
            CompanionConfig config = _read() ?? new CompanionConfig();
            return Discover(config, access, false);
        }

        public string EnsureAccess(bool force)
        {
            bool ignored;
            return EnsureAccess(force, out ignored);
        }

        public string EnsureAccess(bool force, out bool transport)
        {
            transport = false;
            lock (_refreshGate)
            {
                CompanionConfig config = _read() ?? new CompanionConfig();
                if (config.AuthMode != CompanionConfig.ModeDiscord) return null;
                if (config.SessionUnreadable) return null;
                if (!force && AccessCurrent(config)) return config.AccessToken;
                if ((config.RefreshToken ?? "").Length == 0)
                {
                    MarkExpired(config);
                    return null;
                }
                string refresh = config.RefreshToken;
                TokenReply reply = PostToken(config.Address, RefreshBody(refresh), "");
                if (reply.TransportFailed || reply.Status == 408 || reply.Status == 429 || reply.Status >= 500)
                {
                    transport = true;
                    return null;
                }
                if (reply.Status == 401 || reply.Status == 403)
                {
                    MarkExpired(config);
                    return null;
                }
                if (reply.Status != 200) return null;
                if (!reply.Access.StartsWith(CompanionProtocol.AccessPrefix, StringComparison.Ordinal)
                    || !reply.Refresh.StartsWith(CompanionProtocol.RefreshPrefix, StringComparison.Ordinal))
                {
                    MarkExpired(config);
                    return null;
                }
                config.AccessToken = reply.Access;
                config.RefreshToken = reply.Refresh;
                config.AccessExpiresAt = Expiry(reply.ExpiresIn);
                config.SessionStatus = "";
                config.SessionDetail = "";
                _write(config);
                return reply.Access;
            }
        }

        public void NotePermissionDenied()
        {
            lock (_refreshGate)
            {
                CompanionConfig config = _read() ?? new CompanionConfig();
                if (config.SessionStatus == CompanionConfig.StatusDenied) return;
                MarkDenied(config);
            }
        }

        public void NoteSessionExpired()
        {
            lock (_refreshGate)
            {
                CompanionConfig config = _read() ?? new CompanionConfig();
                MarkExpired(config);
            }
        }

        public void RevokeBestEffort()
        {
            CompanionConfig config = _read() ?? new CompanionConfig();
            try
            {
                if ((config.AccessToken ?? "").Length > 0 && AccessCurrent(config))
                {
                    Uri url = Api(config.Address, "/api/companion/logout");
                    if (url != null) Send(url, "POST", "", config.AccessToken, "application/json");
                }
                else if ((config.RefreshToken ?? "").Length > 0)
                {
                    Uri url = Api(config.Address, "/api/companion/revoke");
                    if (url != null) Send(url, "POST", "{\"token\":" + CompanionProtocol.JsonString(config.RefreshToken) + "}", "", "application/json");
                }
            }
            catch (Exception)
            {
            }
        }

        LoginResult StoreAndDiscover(CompanionConfig config, TokenReply exchanged, bool initial)
        {
            config.AuthMode = CompanionConfig.ModeDiscord;
            config.AccessToken = exchanged.Access;
            config.RefreshToken = exchanged.Refresh;
            config.AccessExpiresAt = Expiry(exchanged.ExpiresIn);
            config.SessionUnreadable = false;
            config.SessionStatus = "";
            config.SessionDetail = "";
            _write(config);
            return Discover(config, exchanged.Access, initial);
        }

        LoginResult Discover(CompanionConfig config, string access, bool initial)
        {
            Uri url = Api(config.Address, "/api/companion/guilds");
            if (url == null) return Fail("The site address could not be used.");
            HttpReply reply = Send(url, "GET", "", access, "");
            if (reply.TransportFailed) return Fail("Ironkeep could not be reached.");
            if (reply.Status == 401)
            {
                MarkExpired(config);
                return new LoginResult { Kind = "expired", Detail = "Sign in with Discord again. The legacy key is not used." };
            }
            if (reply.Status == 403 || reply.Status == 404)
            {
                MarkDenied(config);
                return new LoginResult { Kind = "denied", Detail = "This account cannot upload for a guild." };
            }
            if (reply.Status != 200) return Fail("Guilds could not be read.");
            List<CompanionGuild> guilds = ReadGuilds(reply.Body);
            _remember(guilds);
            ApplyGuilds(config, guilds, initial);
            _write(config);
            if (config.SessionStatus == CompanionConfig.StatusDenied)
                return new LoginResult { Kind = "denied", Detail = config.SessionDetail };
            if (config.SessionStatus == CompanionConfig.StatusChoose)
                return new LoginResult { Kind = "choose", Detail = "Choose a guild returned by Ironkeep." };
            return new LoginResult { Kind = "success", Detail = "Uploads go to " + (config.GuildName.Length > 0 ? config.GuildName : config.Slug) + " only." };
        }

        void ApplyGuilds(CompanionConfig config, List<CompanionGuild> guilds, bool initial)
        {
            string selected = (config.Slug ?? "").Trim();
            CompanionGuild match = Find(guilds, selected);
            if (match != null)
            {
                config.Slug = match.Slug;
                config.GuildDiscordId = match.Id;
                config.GuildName = match.Name;
                config.SessionStatus = "";
                config.SessionDetail = "";
                return;
            }
            if (initial && guilds.Count == 1)
            {
                CompanionGuild only = guilds[0];
                config.Slug = only.Slug;
                config.GuildDiscordId = only.Id;
                config.GuildName = only.Name;
                config.SessionStatus = "";
                config.SessionDetail = "";
                return;
            }
            if (guilds.Count == 0)
            {
                config.SessionStatus = CompanionConfig.StatusDenied;
                string name = config.GuildName != null && config.GuildName.Length > 0 ? config.GuildName : selected;
                config.SessionDetail = name.Length == 0
                    ? "No guild has granted Companion upload access."
                    : name + " is no longer authorized for Companion upload.";
                return;
            }
            if (selected.Length > 0)
            {
                config.SessionStatus = CompanionConfig.StatusDenied;
                config.SessionDetail = (config.GuildName.Length > 0 ? config.GuildName : selected) + " is no longer authorized for Companion upload.";
                return;
            }
            config.SessionStatus = CompanionConfig.StatusChoose;
            config.SessionDetail = "Choose a guild returned by Ironkeep.";
        }

        static CompanionGuild Find(List<CompanionGuild> guilds, string slug)
        {
            if (slug == null || slug.Length == 0) return null;
            for (int i = 0; i < guilds.Count; i++)
            {
                if (string.Equals(guilds[i].Slug, slug, StringComparison.OrdinalIgnoreCase)) return guilds[i];
            }
            return null;
        }

        public static List<CompanionGuild> ReadGuilds(string body)
        {
            var found = new List<CompanionGuild>();
            CompanionJson root;
            if (!CompanionProtocol.TryParse(body, out root) || root == null || root.Map == null) return found;
            CompanionJson list;
            if (!root.Map.TryGetValue("guilds", out list) || list == null || list.Items == null) return found;
            for (int i = 0; i < list.Items.Count; i++)
            {
                CompanionJson item = list.Items[i];
                if (item == null || item.Map == null) continue;
                var guild = new CompanionGuild();
                guild.Id = item.String("id");
                guild.Slug = item.String("slug");
                guild.Name = item.String("name");
                if (guild.Slug.Length == 0) continue;
                found.Add(guild);
            }
            return found;
        }

        bool AccessCurrent(CompanionConfig config)
        {
            if ((config.AccessToken ?? "").Length == 0) return false;
            if (!config.AccessToken.StartsWith(CompanionProtocol.AccessPrefix, StringComparison.Ordinal)) return false;
            DateTime expiry;
            if (!DateTime.TryParse(config.AccessExpiresAt, System.Globalization.CultureInfo.InvariantCulture, System.Globalization.DateTimeStyles.RoundtripKind, out expiry))
                return false;
            if (expiry.Kind == DateTimeKind.Unspecified) expiry = DateTime.SpecifyKind(expiry, DateTimeKind.Utc);
            return expiry.ToUniversalTime() > Clock().AddSeconds(30);
        }

        string Expiry(int expiresIn)
        {
            int seconds = expiresIn > 30 ? expiresIn - 30 : 0;
            return Clock().AddSeconds(seconds).ToUniversalTime().ToString("o", System.Globalization.CultureInfo.InvariantCulture);
        }

        void MarkExpired(CompanionConfig config)
        {
            config.AuthMode = CompanionConfig.ModeDiscord;
            config.AccessToken = "";
            config.RefreshToken = "";
            config.AccessExpiresAt = "";
            config.SessionStatus = CompanionConfig.StatusExpired;
            config.SessionDetail = "Sign in with Discord again. The legacy key is not used.";
            _write(config);
        }

        void MarkDenied(CompanionConfig config)
        {
            config.AuthMode = CompanionConfig.ModeDiscord;
            config.SessionStatus = CompanionConfig.StatusDenied;
            config.SessionDetail = "This account cannot upload for a guild.";
            _write(config);
        }

        static LoginResult Fail(string detail)
        {
            return Fail("failed", detail);
        }

        static LoginResult Fail(string kind, string detail)
        {
            return new LoginResult { Kind = kind, Detail = CompanionProtocol.SafeDetail(detail) };
        }

        TokenReply PostToken(string address, string body, string bearer)
        {
            var reply = new TokenReply();
            Uri url = Api(address, "/api/companion/token");
            if (url == null)
            {
                reply.TransportFailed = true;
                return reply;
            }
            HttpReply http = Send(url, "POST", body, bearer, "application/json");
            reply.Status = http.Status;
            reply.TransportFailed = http.TransportFailed;
            reply.Body = "";
            if (http.Status != 200 || http.TransportFailed) return reply;
            CompanionJson root;
            if (!CompanionProtocol.TryParse(http.Body, out root) || root == null || !root.OkTrue()) return reply;
            reply.Access = root.String("access_token");
            reply.Refresh = root.String("refresh_token");
            reply.ExpiresIn = root.Int("expires_in", 0);
            return reply;
        }

        static string AuthorizationBody(string code, string verifier, string redirect)
        {
            return "{\"grant_type\":\"authorization_code\",\"code\":" + CompanionProtocol.JsonString(code)
                + ",\"code_verifier\":" + CompanionProtocol.JsonString(verifier)
                + ",\"redirect_uri\":" + CompanionProtocol.JsonString(redirect) + "}";
        }

        static string RefreshBody(string refresh)
        {
            return "{\"grant_type\":\"refresh_token\",\"refresh_token\":" + CompanionProtocol.JsonString(refresh) + "}";
        }

        public static Uri Api(string address, string path)
        {
            string problem;
            Uri probe = SiteClient.Target(address, "local", out problem);
            if (probe == null) return null;
            var builder = new UriBuilder(probe);
            builder.Path = path;
            builder.Query = "";
            return builder.Uri;
        }

        public static Uri AttendanceUri(string address, string slug)
        {
            string problem;
            Uri probe = SiteClient.Target(address, slug, out problem);
            if (probe == null) return null;
            string lowered = (slug ?? "").Trim().ToLowerInvariant();
            var builder = new UriBuilder(probe);
            builder.Path = "/api/companion/guilds/" + lowered + "/attendance";
            builder.Query = "";
            return builder.Uri;
        }

        public static HttpReply Send(Uri url, string method, string body, string bearer, string contentType)
        {
            var reply = new HttpReply();
            var request = (HttpWebRequest)WebRequest.Create(url);
            request.Method = method;
            request.Timeout = 20000;
            request.ReadWriteTimeout = 20000;
            request.UserAgent = "IronkeepCompanion/2.0";
            if (bearer != null && bearer.Length > 0) request.Headers["Authorization"] = "Bearer " + bearer;
            if (string.Equals(method, "POST", StringComparison.Ordinal))
            {
                byte[] bytes = Encoding.UTF8.GetBytes(body ?? "");
                request.ContentType = contentType == null || contentType.Length == 0 ? "application/json" : contentType;
                request.ContentLength = bytes.Length;
                using (Stream stream = request.GetRequestStream())
                    stream.Write(bytes, 0, bytes.Length);
            }
            try
            {
                using (var response = (HttpWebResponse)request.GetResponse())
                using (var reader = new StreamReader(response.GetResponseStream(), Encoding.UTF8))
                {
                    reply.Status = (int)response.StatusCode;
                    reply.Body = reader.ReadToEnd();
                    return reply;
                }
            }
            catch (WebException ex)
            {
                var response = ex.Response as HttpWebResponse;
                if (response == null)
                {
                    reply.TransportFailed = true;
                    return reply;
                }
                reply.Status = (int)response.StatusCode;
                using (var reader = new StreamReader(response.GetResponseStream(), Encoding.UTF8))
                    reply.Body = reader.ReadToEnd();
                return reply;
            }
        }
    }

    public sealed class HttpReply
    {
        public int Status;
        public bool TransportFailed;
        public string Body = "";
    }

    /// <summary>
    /// Uploads a queued snapshot to the guild id stored on that snapshot.
    /// A Discord failure never selects the legacy key, and a mismatched guild is not sent.
    /// </summary>
    public sealed class DiscordUploader : IReportUploader
    {
        readonly Func<CompanionConfig> _read;
        readonly DiscordLogin _login;

        public DiscordUploader(Func<CompanionConfig> read, DiscordLogin login)
        {
            if (read == null) throw new ArgumentNullException("read");
            if (login == null) throw new ArgumentNullException("login");
            _read = read;
            _login = login;
        }

        public UploadResult Upload(string guildId, string body)
        {
            CompanionConfig config = _read() ?? new CompanionConfig();
            if (config.AuthMode != CompanionConfig.ModeDiscord)
                return Denied();
            string status = config.SessionStatus ?? "";
            if (status.Length > 0)
                return status == CompanionConfig.StatusExpired ? Unauthorized() : Denied();
            string selected = (config.Slug ?? "").Trim();
            if (selected.Length == 0 || guildId == null || !string.Equals(guildId.Trim(), selected, StringComparison.OrdinalIgnoreCase))
                return Denied();
            bool transport;
            string access = _login.EnsureAccess(false, out transport);
            if (access == null || access.Length == 0) return transport ? Offline() : Unauthorized();
            UploadResult first = Post(config.Address, selected, access, body);
            if (first.Status == 401)
            {
                access = _login.EnsureAccess(true, out transport);
                if (access == null || access.Length == 0) return transport ? Offline() : Unauthorized();
                first = Post(config.Address, selected, access, body);
                if (first.Status == 401)
                {
                    _login.NoteSessionExpired();
                    return Unauthorized();
                }
            }
            if (first.Status == 403) _login.NotePermissionDenied();
            return first;
        }

        static UploadResult Post(string address, string slug, string access, string body)
        {
            Uri url = DiscordLogin.AttendanceUri(address, slug);
            if (url == null) return Denied();
            try
            {
                int status;
                string response = SiteClient.Post(url, access, body, out status);
                return new UploadResult { Status = status, Body = response ?? "" };
            }
            catch (WebException)
            {
                return new UploadResult { Status = 0, Body = "", TransportFailed = true };
            }
        }

        static UploadResult Denied()
        {
            return new UploadResult { Status = 403, Body = "{\"ok\":false}" };
        }

        static UploadResult Unauthorized()
        {
            return new UploadResult { Status = 401, Body = "{\"ok\":false}" };
        }

        static UploadResult Offline()
        {
            return new UploadResult { Status = 0, Body = "", TransportFailed = true };
        }
    }

    public sealed class SessionUploader : IReportUploader
    {
        readonly Func<CompanionConfig> _read;
        readonly DiscordUploader _discord;
        readonly LegacyUploader _legacy;

        public SessionUploader(Func<CompanionConfig> read, DiscordUploader discord, LegacyUploader legacy)
        {
            _read = read;
            _discord = discord;
            _legacy = legacy;
        }

        public UploadResult Upload(string guildId, string body)
        {
            CompanionConfig config = _read() ?? new CompanionConfig();
            if (config.AuthMode == CompanionConfig.ModeDiscord) return _discord.Upload(guildId, body);
            if (config.IsLegacy) return _legacy.Upload(guildId, body);
            return new UploadResult { Status = 401, Body = "{\"ok\":false}" };
        }
    }
}
