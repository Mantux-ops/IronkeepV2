using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Security.Cryptography;
using System.Text;

namespace Ironkeep
{
    public interface IProtector
    {
        bool IsProtected(string stored);
        string Protect(string plain);
        string Unprotect(string stored);
    }

    public sealed class DpapiProtector : IProtector
    {
        public bool IsProtected(string stored)
        {
            return stored != null && stored.StartsWith("dpapi:", StringComparison.Ordinal);
        }

        public string Protect(string plain)
        {
            byte[] raw = Encoding.UTF8.GetBytes(plain ?? "");
            byte[] blob = ProtectedData.Protect(raw, null, DataProtectionScope.CurrentUser);
            return "dpapi:" + Convert.ToBase64String(blob);
        }

        public string Unprotect(string stored)
        {
            if (!IsProtected(stored)) throw new CryptographicException("unprotected");
            byte[] blob = Convert.FromBase64String(stored.Substring("dpapi:".Length));
            byte[] raw = ProtectedData.Unprotect(blob, null, DataProtectionScope.CurrentUser);
            return Encoding.UTF8.GetString(raw);
        }
    }

    public sealed class PrefixProtector : IProtector
    {
        public bool IsProtected(string stored)
        {
            return stored != null && stored.StartsWith("test:", StringComparison.Ordinal);
        }

        public string Protect(string plain)
        {
            return "test:" + Convert.ToBase64String(Encoding.UTF8.GetBytes(plain ?? ""));
        }

        public string Unprotect(string stored)
        {
            if (!IsProtected(stored)) throw new FormatException("unprotected");
            return Encoding.UTF8.GetString(Convert.FromBase64String(stored.Substring("test:".Length)));
        }
    }

    public sealed class SiteSettings
    {
        public string Address = "";
        public string Slug = "";
        public string Token = "";
        public bool Unreadable;
    }

    public sealed class SiteStore
    {
        readonly string file;
        readonly IProtector protector;

        public SiteStore(string file, IProtector protector)
        {
            this.file = file;
            this.protector = protector;
        }

        public static string Folder()
        {
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "Ironkeep");
        }

        public static SiteStore ForUser()
        {
            return new SiteStore(Path.Combine(Folder(), "companion-site.txt"), new DpapiProtector());
        }

        public SiteSettings Load()
        {
            var site = new SiteSettings();
            try
            {
                if (!File.Exists(file)) return site;
                string[] lines = File.ReadAllLines(file);
                if (lines.Length > 0) site.Address = lines[0].Trim();
                if (lines.Length > 1) site.Slug = lines[1].Trim();
                string raw = lines.Length > 2 ? lines[2].Trim() : "";
                if (raw.Length == 0) return site;
                if (protector.IsProtected(raw))
                {
                    try
                    {
                        site.Token = protector.Unprotect(raw);
                    }
                    catch (CryptographicException)
                    {
                        site.Unreadable = true;
                    }
                    catch (FormatException)
                    {
                        site.Unreadable = true;
                    }
                    return site;
                }
                site.Token = raw;
                Save(site.Address, site.Slug, site.Token);
            }
            catch (IOException)
            {
            }
            catch (UnauthorizedAccessException)
            {
            }
            return site;
        }

        public void Save(string address, string slug, string token)
        {
            string stored = token ?? "";
            if (stored.Length > 0 && !protector.IsProtected(stored))
            {
                try
                {
                    stored = protector.Protect(stored);
                }
                catch (CryptographicException)
                {
                    stored = token ?? "";
                }
            }
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(file));
                File.WriteAllLines(file, new string[] { (address ?? "").Trim(), (slug ?? "").Trim(), stored });
            }
            catch (IOException)
            {
            }
            catch (UnauthorizedAccessException)
            {
            }
        }
    }

    public enum SendOutcome
    {
        Sent,
        Skipped,
        Auth,
        Rejected,
        Offline
    }

    public static class SiteClient
    {
        public static Uri Target(string address, string slug, out string problem)
        {
            problem = "";
            address = (address ?? "").Trim();
            slug = (slug ?? "").Trim().ToLowerInvariant();
            if (!SlugOk(slug))
            {
                problem = "Vul de gildenaam in. Die staat in het adres van jullie raids-pagina.";
                return null;
            }
            Uri uri;
            if (!Uri.TryCreate(address, UriKind.Absolute, out uri))
            {
                problem = "Het adres klopt niet. Gebruik https://ironkeep.gg.";
                return null;
            }
            bool local = string.Equals(uri.Host, "localhost", StringComparison.OrdinalIgnoreCase) || uri.Host == "127.0.0.1";
            if (uri.Scheme != "https" && !(uri.Scheme == "http" && local))
            {
                problem = "Het adres moet met https:// beginnen.";
                return null;
            }
            if (uri.UserInfo != null && uri.UserInfo.Length > 0)
            {
                problem = "Het adres klopt niet.";
                return null;
            }
            var builder = new UriBuilder(uri.Scheme, uri.Host, uri.IsDefaultPort ? -1 : uri.Port);
            builder.Path = "/api/" + slug + "/attendance";
            return builder.Uri;
        }

        public static bool SlugOk(string slug)
        {
            if (slug == null || slug.Length < 1 || slug.Length > 32) return false;
            for (int i = 0; i < slug.Length; i++)
            {
                char c = slug[i];
                bool ok = (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-';
                if (!ok) return false;
                if (c == '-' && (i == 0 || i == slug.Length - 1)) return false;
            }
            return true;
        }

        public static string Post(Uri url, string token, string body, out int status)
        {
            status = 0;
            var request = (HttpWebRequest)WebRequest.Create(url);
            request.Method = "POST";
            request.ContentType = "text/plain; charset=utf-8";
            request.Headers["Authorization"] = "Bearer " + token;
            request.Timeout = 20000;
            request.ReadWriteTimeout = 20000;
            request.UserAgent = "IronkeepCompanion/1.0";
            byte[] bytes = Encoding.UTF8.GetBytes(body ?? "");
            request.ContentLength = bytes.Length;
            using (Stream stream = request.GetRequestStream())
                stream.Write(bytes, 0, bytes.Length);
            try
            {
                using (var response = (HttpWebResponse)request.GetResponse())
                using (var reader = new StreamReader(response.GetResponseStream(), Encoding.UTF8))
                {
                    status = (int)response.StatusCode;
                    return reader.ReadToEnd();
                }
            }
            catch (WebException ex)
            {
                var response = ex.Response as HttpWebResponse;
                if (response == null) throw;
                status = (int)response.StatusCode;
                using (var reader = new StreamReader(response.GetResponseStream(), Encoding.UTF8))
                    return reader.ReadToEnd();
            }
        }

        public static bool Accepted(string body)
        {
            if (body == null) return false;
            return body.IndexOf("\"ok\":true", StringComparison.Ordinal) >= 0
                || body.IndexOf("\"ok\": true", StringComparison.Ordinal) >= 0;
        }

        public static bool Duplicate(string body)
        {
            if (body == null) return false;
            return body.IndexOf("\"duplicate\":true", StringComparison.Ordinal) >= 0
                || body.IndexOf("\"duplicate\": true", StringComparison.Ordinal) >= 0;
        }

        public static bool Retryable(int status)
        {
            if (status == 0 || status == 408 || status == 429) return true;
            return status >= 500 && status <= 599;
        }
    }

    public static class ReportHash
    {
        public static string Of(string text)
        {
            byte[] raw = Encoding.UTF8.GetBytes(text ?? "");
            byte[] hash;
            using (SHA256 sha = SHA256.Create())
                hash = sha.ComputeHash(raw);
            var chars = new StringBuilder(hash.Length * 2);
            for (int i = 0; i < hash.Length; i++)
                chars.Append(hash[i].ToString("x2"));
            return chars.ToString();
        }
    }

    public sealed class SendLedger
    {
        readonly string file;
        readonly Dictionary<string, string> sent = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

        public SendLedger(string file)
        {
            this.file = file;
            Load();
        }

        public static SendLedger ForUser()
        {
            return new SendLedger(Path.Combine(SiteStore.Folder(), "companion-sent.txt"));
        }

        public static string Key(string path)
        {
            if (path == null) return "";
            try
            {
                path = Path.GetFullPath(path);
            }
            catch (ArgumentException)
            {
            }
            catch (NotSupportedException)
            {
            }
            if (Path.DirectorySeparatorChar == '\\') return path.ToLowerInvariant();
            return path;
        }

        public bool Has(string path, string hash)
        {
            string known;
            return sent.TryGetValue(Key(path), out known) && known == hash;
        }

        public void Remember(string path, string hash)
        {
            sent[Key(path)] = hash ?? "";
            Write();
        }

        void Load()
        {
            try
            {
                if (!File.Exists(file)) return;
                string[] lines = File.ReadAllLines(file);
                for (int i = 0; i < lines.Length; i++)
                {
                    int tab = lines[i].IndexOf('\t');
                    if (tab <= 0) continue;
                    sent[lines[i].Substring(tab + 1)] = lines[i].Substring(0, tab);
                }
            }
            catch (IOException)
            {
            }
            catch (UnauthorizedAccessException)
            {
            }
        }

        void Write()
        {
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(file));
                var lines = new List<string>();
                foreach (var pair in sent)
                    lines.Add(pair.Value + "\t" + pair.Key);
                File.WriteAllLines(file, lines.ToArray());
            }
            catch (IOException)
            {
            }
            catch (UnauthorizedAccessException)
            {
            }
        }
    }

    public sealed class SettleWatch
    {
        long seen = -1;

        public void Reset()
        {
            seen = -1;
        }

        public bool Due(long length)
        {
            if (length < 0) return false;
            if (seen != length)
            {
                seen = length;
                return false;
            }
            seen = -1;
            return true;
        }
    }

    public static class SendRetry
    {
        public static int Seconds(int attempt)
        {
            if (attempt <= 1) return 15;
            if (attempt == 2) return 60;
            if (attempt == 3) return 300;
            return 0;
        }
    }
}
