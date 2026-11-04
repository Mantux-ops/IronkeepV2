using System;
using System.IO;
using System.Security.Cryptography;
using Ironkeep;

namespace Ironkeep.Companion
{
    public sealed class CompanionConfig
    {
        public string Address = "https://ironkeep.gg";
        public string Slug = "";
        public string Token = "";
        public bool TokenUnreadable;
        public string WowFolder = "";
        public bool StartWithWindows;
        public bool TrayExplained;
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
            return config;
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
            File.WriteAllLines(temp, new string[]
            {
                (config.Address ?? "").Trim(),
                (config.Slug ?? "").Trim(),
                stored,
                (config.WowFolder ?? "").Trim(),
                config.StartWithWindows ? "1" : "0",
                config.TrayExplained ? "1" : "0"
            });
            if (File.Exists(_path)) File.Delete(_path);
            File.Move(temp, _path);
            QueueStore.Restrict(_path);
        }
    }
}
