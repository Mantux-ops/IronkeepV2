using System;
using System.IO;
using System.Security.Cryptography;
using Ironkeep;

namespace Ironkeep.Companion
{
    public sealed class CompanionConfig
    {
        public const string ModeDiscord = "discord";
        public const string ModeLegacy = "legacy";
        public const string ModeSignedOut = "signed-out";
        public const string StatusExpired = "expired";
        public const string StatusDenied = "denied";
        public const string StatusFailed = "failed";
        public const string StatusChoose = "choose";

        public string Address = "https://ironkeep.gg";
        public string Slug = "";
        public string Token = "";
        public bool TokenUnreadable;
        public string WowFolder = "";
        public bool StartWithWindows;
        public bool TrayExplained;
        public string AuthMode = "";
        public string AccessToken = "";
        public string RefreshToken = "";
        public string AccessExpiresAt = "";
        public string GuildDiscordId = "";
        public string GuildName = "";
        public string SessionStatus = "";
        public string SessionDetail = "";
        public bool SessionUnreadable;

        public bool IsLegacy
        {
            get
            {
                if (AuthMode == ModeDiscord || AuthMode == ModeSignedOut) return false;
                if (AuthMode == ModeLegacy) return true;
                return (Token ?? "").Length > 0;
            }
        }

        public void CopySession(CompanionConfig source)
        {
            if (source == null) return;
            AuthMode = source.AuthMode ?? "";
            AccessToken = source.AccessToken ?? "";
            RefreshToken = source.RefreshToken ?? "";
            AccessExpiresAt = source.AccessExpiresAt ?? "";
            GuildDiscordId = source.GuildDiscordId ?? "";
            GuildName = source.GuildName ?? "";
            SessionStatus = source.SessionStatus ?? "";
            SessionDetail = source.SessionDetail ?? "";
            SessionUnreadable = source.SessionUnreadable;
        }

        public void ClearDiscordSecrets()
        {
            AccessToken = "";
            RefreshToken = "";
            AccessExpiresAt = "";
            SessionStatus = "";
            SessionDetail = "";
            SessionUnreadable = false;
        }
    }

    /// <summary>
    /// Settings for the WPF companion. The API key is stored only after Protect succeeds.
    /// A plaintext key already on disk is refused.
    /// </summary>
    public sealed class CompanionConfigStore
    {
        readonly string _path;
        readonly IProtector _protector;

        public CompanionConfigStore(string path, IProtector protector)
        {
            if (path == null || path.Trim().Length == 0) throw new ArgumentException("Settings path is required.");
            if (protector == null) throw new ArgumentNullException("protector");
            _path = path;
            _protector = protector;
        }

        public CompanionConfig Load()
        {
            var config = new CompanionConfig();
            if (!File.Exists(_path)) return config;
            string[] lines = File.ReadAllLines(_path);
            if (lines.Length > 0 && lines[0].Trim().Length > 0) config.Address = lines[0].Trim();
            if (lines.Length > 1) config.Slug = lines[1].Trim();
            string raw = lines.Length > 2 ? lines[2].Trim() : "";
            if (raw.Length > 0)
            {
                if (!_protector.IsProtected(raw)) config.TokenUnreadable = true;
                else
                {
                    try
                    {
                        config.Token = _protector.Unprotect(raw);
                    }
                    catch (CryptographicException)
                    {
                        config.TokenUnreadable = true;
                    }
                    catch (FormatException)
                    {
                        config.TokenUnreadable = true;
                    }
                }
            }
            if (lines.Length > 3) config.WowFolder = lines[3].Trim();
            if (lines.Length > 4) config.StartWithWindows = lines[4].Trim() == "1";
            if (lines.Length > 5) config.TrayExplained = lines[5].Trim() == "1";
            if (lines.Length > 6) config.AuthMode = lines[6].Trim();
            config.AccessToken = ReadSecret(lines, 7, config);
            config.RefreshToken = ReadSecret(lines, 8, config);
            if (lines.Length > 9) config.AccessExpiresAt = lines[9].Trim();
            if (lines.Length > 10) config.GuildDiscordId = lines[10].Trim();
            if (lines.Length > 11) config.GuildName = lines[11].Trim();
            if (lines.Length > 12) config.SessionStatus = lines[12].Trim();
            if (lines.Length > 13) config.SessionDetail = lines[13].Trim();
            if (config.SessionUnreadable)
            {
                config.AccessToken = "";
                config.RefreshToken = "";
            }
            return config;
        }

        string ReadSecret(string[] lines, int index, CompanionConfig config)
        {
            string raw = lines.Length > index ? lines[index].Trim() : "";
            if (raw.Length == 0) return "";
            if (!_protector.IsProtected(raw))
            {
                config.SessionUnreadable = true;
                return "";
            }
            try
            {
                return _protector.Unprotect(raw);
            }
            catch (CryptographicException)
            {
                config.SessionUnreadable = true;
                return "";
            }
            catch (FormatException)
            {
                config.SessionUnreadable = true;
                return "";
            }
        }

        string ProtectSecret(string plain)
        {
            string token = plain ?? "";
            if (token.Length == 0) return "";
            if (_protector.IsProtected(token)) return token;
            string stored;
            try
            {
                stored = _protector.Protect(token);
            }
            catch (CryptographicException ex)
            {
                throw new InvalidOperationException("The Discord session could not be protected. It was not saved.", ex);
            }
            catch (PlatformNotSupportedException ex)
            {
                throw new InvalidOperationException("The Discord session could not be protected. It was not saved.", ex);
            }
            if (!_protector.IsProtected(stored))
                throw new InvalidOperationException("The Discord session could not be protected. It was not saved.");
            return stored;
        }

        public void Save(CompanionConfig config)
        {
            if (config == null) throw new ArgumentNullException("config");
            string token = config.Token ?? "";
            string stored = "";
            if (token.Length > 0)
            {
                if (_protector.IsProtected(token)) stored = token;
                else
                {
                    try
                    {
                        stored = _protector.Protect(token);
                    }
                    catch (CryptographicException ex)
                    {
                        throw new InvalidOperationException("The API key could not be protected. It was not saved.", ex);
                    }
                    catch (PlatformNotSupportedException ex)
                    {
                        throw new InvalidOperationException("The API key could not be protected. It was not saved.", ex);
                    }
                }
                if (!_protector.IsProtected(stored))
                    throw new InvalidOperationException("The API key could not be protected. It was not saved.");
            }
            string directory = Path.GetDirectoryName(_path);
            if (directory != null && directory.Length > 0) Directory.CreateDirectory(directory);
            string temp = _path + ".tmp";
            string access = ProtectSecret(config.AccessToken);
            string refresh = ProtectSecret(config.RefreshToken);
            File.WriteAllLines(temp, new string[]
            {
                (config.Address ?? "").Trim(),
                (config.Slug ?? "").Trim(),
                stored,
                (config.WowFolder ?? "").Trim(),
                config.StartWithWindows ? "1" : "0",
                config.TrayExplained ? "1" : "0",
                (config.AuthMode ?? "").Trim(),
                access,
                refresh,
                (config.AccessExpiresAt ?? "").Trim(),
                (config.GuildDiscordId ?? "").Trim(),
                (config.GuildName ?? "").Replace("\r", " ").Replace("\n", " ").Trim(),
                (config.SessionStatus ?? "").Trim(),
                CompanionProtocol.SafeDetail(config.SessionDetail).Replace("\r", " ").Replace("\n", " ")
            });
            if (File.Exists(_path)) File.Delete(_path);
            File.Move(temp, _path);
            QueueStore.Restrict(_path);
        }
    }
}
