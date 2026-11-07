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
            return ReadAck(body) == AckKind.Accepted;
        }

        /// <summary>
        /// Accepted: one JSON object with a boolean ok property set to true.
        /// Rejected: one JSON object with boolean ok set to false.
        /// Unparseable: anything else, including truncated JSON and text that only contains the characters "ok":true.
        /// </summary>
        public static AckKind ReadAck(string body)
        {
            JsonValue value;
            if (!AckJson.TryParse(body, out value) || value == null || value.Object == null) return AckKind.Unparseable;
            JsonValue ok;
            if (!value.Object.TryGetValue("ok", out ok) || ok == null || !ok.IsBool) return AckKind.Unparseable;
            return ok.Bool ? AckKind.Accepted : AckKind.Rejected;
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

    public enum AckKind
    {
        Accepted,
        Rejected,
        Unparseable
    }

    static class AckJson
    {
        public static bool TryParse(string body, out JsonValue value)
        {
            value = null;
            var cursor = new JsonCursor(body);
            if (!cursor.ParseValue(0, out value)) return false;
            cursor.SkipWs();
            return cursor.Ended;
        }

        sealed class JsonCursor
        {
            readonly string _text;
            int _index;

            public JsonCursor(string text)
            {
                _text = text ?? "";
                if (_text.Length > 0 && _text[0] == '\uFEFF') _index = 1;
            }

            public bool Ended { get { return _index >= _text.Length; } }

            public void SkipWs()
            {
                while (_index < _text.Length && char.IsWhiteSpace(_text[_index])) _index++;
            }

            public bool ParseValue(int depth, out JsonValue value)
            {
                value = null;
                if (depth > 32) return false;
                SkipWs();
                if (_index >= _text.Length) return false;
                char ch = _text[_index];
                if (ch == '{') return ParseObject(depth, out value);
                if (ch == '[') return ParseArray(depth, out value);
                if (ch == '"')
                {
                    string text;
                    if (!ParseString(out text)) return false;
                    value = JsonValue.Text(text);
                    return true;
                }
                if (ch == 't') return Literal("true", JsonValue.FromBool(true), out value);
                if (ch == 'f') return Literal("false", JsonValue.FromBool(false), out value);
                if (ch == 'n') return Literal("null", JsonValue.Null(), out value);
                if (ch == '-' || (ch >= '0' && ch <= '9')) return ParseNumber(out value);
                return false;
            }

            bool ParseObject(int depth, out JsonValue value)
            {
                value = null;
                _index++;
                var map = new Dictionary<string, JsonValue>();
                SkipWs();
                if (Eat('}'))
                {
                    value = JsonValue.Obj(map);
                    return true;
                }
                while (true)
                {
                    SkipWs();
                    string key;
                    if (!ParseString(out key)) return false;
                    if (map.ContainsKey(key)) return false;
                    SkipWs();
                    if (!Eat(':')) return false;
                    JsonValue child;
                    if (!ParseValue(depth + 1, out child)) return false;
                    map[key] = child;
                    SkipWs();
                    if (Eat('}'))
                    {
                        value = JsonValue.Obj(map);
                        return true;
                    }
                    if (!Eat(',')) return false;
                }
            }

            bool ParseArray(int depth, out JsonValue value)
            {
                value = null;
                _index++;
                SkipWs();
                if (Eat(']'))
                {
                    value = JsonValue.Other();
                    return true;
                }
                while (true)
                {
                    JsonValue child;
                    if (!ParseValue(depth + 1, out child)) return false;
                    SkipWs();
                    if (Eat(']'))
                    {
                        value = JsonValue.Other();
                        return true;
                    }
                    if (!Eat(',')) return false;
                }
            }

            bool ParseString(out string text)
            {
                text = null;
                if (!Eat('"')) return false;
                var built = new StringBuilder();
                while (_index < _text.Length)
                {
                    char ch = _text[_index++];
                    if (ch == '"')
                    {
                        text = built.ToString();
                        return true;
                    }
                    if (ch == '\\')
                    {
                        if (_index >= _text.Length) return false;
                        char escaped = _text[_index++];
                        if (escaped == '"' || escaped == '\\' || escaped == '/') built.Append(escaped);
                        else if (escaped == 'b') built.Append('\b');
                        else if (escaped == 'f') built.Append('\f');
                        else if (escaped == 'n') built.Append('\n');
                        else if (escaped == 'r') built.Append('\r');
                        else if (escaped == 't') built.Append('\t');
                        else if (escaped == 'u')
                        {
                            int code;
                            if (!Hex4(out code)) return false;
                            built.Append((char)code);
                        }
                        else return false;
                    }
                    else if (ch < ' ') return false;
                    else built.Append(ch);
                }
                return false;
            }

            bool ParseNumber(out JsonValue value)
            {
                value = null;
                int start = _index;
                if (_text[_index] == '-') _index++;
                if (_index >= _text.Length || _text[_index] < '0' || _text[_index] > '9') return false;
                if (_text[_index] == '0')
                {
                    _index++;
                    if (_index < _text.Length && _text[_index] >= '0' && _text[_index] <= '9') return false;
                }
                else while (_index < _text.Length && _text[_index] >= '0' && _text[_index] <= '9') _index++;
                if (_index < _text.Length && _text[_index] == '.')
                {
                    _index++;
                    int digits = 0;
                    while (_index < _text.Length && _text[_index] >= '0' && _text[_index] <= '9')
                    {
                        _index++;
                        digits++;
                    }
                    if (digits == 0) return false;
                }
                if (_index < _text.Length && (_text[_index] == 'e' || _text[_index] == 'E'))
                {
                    _index++;
                    if (_index < _text.Length && (_text[_index] == '+' || _text[_index] == '-')) _index++;
                    int digits = 0;
                    while (_index < _text.Length && _text[_index] >= '0' && _text[_index] <= '9')
                    {
                        _index++;
                        digits++;
                    }
                    if (digits == 0) return false;
                }
                if (_index == start) return false;
                value = JsonValue.Other();
                return true;
            }

            bool Literal(string word, JsonValue made, out JsonValue value)
            {
                value = null;
                if (_index + word.Length > _text.Length) return false;
                if (string.CompareOrdinal(_text, _index, word, 0, word.Length) != 0) return false;
                _index += word.Length;
                value = made;
                return true;
            }

            bool Hex4(out int code)
            {
                code = 0;
                if (_index + 4 > _text.Length) return false;
                for (int i = 0; i < 4; i++)
                {
                    char ch = _text[_index++];
                    int digit;
                    if (ch >= '0' && ch <= '9') digit = ch - '0';
                    else if (ch >= 'a' && ch <= 'f') digit = ch - 'a' + 10;
                    else if (ch >= 'A' && ch <= 'F') digit = ch - 'A' + 10;
                    else return false;
                    code = (code << 4) + digit;
                }
                return true;
            }

            bool Eat(char expected)
            {
                if (_index >= _text.Length || _text[_index] != expected) return false;
                _index++;
                return true;
            }
        }
    }

    sealed class JsonValue
    {
        public Dictionary<string, JsonValue> Object;
        public bool IsBool;
        public bool Bool;

        public static JsonValue Obj(Dictionary<string, JsonValue> map)
        {
            var value = new JsonValue();
            value.Object = map;
            return value;
        }

        public static JsonValue FromBool(bool bit)
        {
            var value = new JsonValue();
            value.IsBool = true;
            value.Bool = bit;
            return value;
        }

        public static JsonValue Text(string text)
        {
            return new JsonValue();
        }

        public static JsonValue Null()
        {
            return new JsonValue();
        }

        public static JsonValue Other()
        {
            return new JsonValue();
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
