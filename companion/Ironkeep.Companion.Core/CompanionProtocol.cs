using System;
using System.Collections.Generic;
using System.Security.Cryptography;
using System.Text;

namespace Ironkeep.Companion
{
    public enum CompanionAuthState
    {
        NotConnected,
        Connecting,
        AwaitingApproval,
        Connected,
        GuildSelectionRequired,
        Ready,
        SessionExpired,
        PermissionDenied,
        ConnectionFailed
    }

    public sealed class CompanionGuild
    {
        public string Id = "";
        public string Slug = "";
        public string Name = "";

        public override string ToString()
        {
            if (Name != null && Name.Length > 0) return Name;
            return Slug ?? "";
        }
    }

    public sealed class LoginResult
    {
        public string Kind = "";
        public string Detail = "";

        public bool Succeeded { get { return Kind == "success"; } }
    }

    /// <summary>
    /// Phase 3 companion contract. The public client id is not a Discord credential.
    /// Redirects are http://127.0.0.1:{port}/callback with PKCE S256.
    /// </summary>
    public static class CompanionProtocol
    {
        public const string ClientId = "ironkeep-companion";
        public const string AccessPrefix = "ika.";
        public const string RefreshPrefix = "ikr.";
        const string Alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~";

        public static string Label(CompanionAuthState state)
        {
            if (state == CompanionAuthState.Connecting) return "Connecting";
            if (state == CompanionAuthState.AwaitingApproval) return "Awaiting browser approval";
            if (state == CompanionAuthState.Connected) return "Connected";
            if (state == CompanionAuthState.GuildSelectionRequired) return "Guild selection required";
            if (state == CompanionAuthState.Ready) return "Ready to sync";
            if (state == CompanionAuthState.SessionExpired) return "Session expired";
            if (state == CompanionAuthState.PermissionDenied) return "Permission denied";
            if (state == CompanionAuthState.ConnectionFailed) return "Connection failed";
            return "Not connected";
        }

        public static string RandomSecret(int length)
        {
            if (length < 16) length = 16;
            if (length > 128) length = 128;
            var chars = new char[length];
            for (int i = 0; i < length; i++)
                chars[i] = Alphabet[RandomNumberGenerator.GetInt32(Alphabet.Length)];
            return new string(chars);
        }

        public static string ChallengeS256(string verifier)
        {
            byte[] hash = SHA256.HashData(Encoding.ASCII.GetBytes(verifier ?? ""));
            string encoded = Convert.ToBase64String(hash);
            return encoded.TrimEnd('=').Replace('+', '-').Replace('/', '_');
        }

        public static bool FixedEqual(string left, string right)
        {
            byte[] a = Encoding.UTF8.GetBytes(left ?? "");
            byte[] b = Encoding.UTF8.GetBytes(right ?? "");
            return CryptographicOperations.FixedTimeEquals(a, b);
        }

        public static string ConnectUrl(string origin, string redirectUri, string state, string challenge)
        {
            string root = (origin ?? "").Trim().TrimEnd('/');
            var query = new StringBuilder();
            query.Append("response_type=code");
            query.Append("&client_id=").Append(Uri.EscapeDataString(ClientId));
            query.Append("&redirect_uri=").Append(Uri.EscapeDataString(redirectUri ?? ""));
            query.Append("&state=").Append(Uri.EscapeDataString(state ?? ""));
            query.Append("&code_challenge=").Append(Uri.EscapeDataString(challenge ?? ""));
            query.Append("&code_challenge_method=S256");
            return root + "/companion/connect?" + query.ToString();
        }

        public static string SafeDetail(string text)
        {
            if (text == null) return "";
            if (text.IndexOf(AccessPrefix, StringComparison.Ordinal) >= 0) return "The connection did not complete.";
            if (text.IndexOf(RefreshPrefix, StringComparison.Ordinal) >= 0) return "The connection did not complete.";
            if (text.IndexOf("ikn.", StringComparison.Ordinal) >= 0) return "The connection did not complete.";
            if (text.Length > 180) return text.Substring(0, 180);
            return text;
        }

        public static string JsonString(string value)
        {
            var built = new StringBuilder();
            built.Append('"');
            string text = value ?? "";
            for (int i = 0; i < text.Length; i++)
            {
                char ch = text[i];
                if (ch == '\\' || ch == '"')
                {
                    built.Append('\\');
                    built.Append(ch);
                }
                else if (ch == '\n') built.Append("\\n");
                else if (ch == '\r') built.Append("\\r");
                else if (ch == '\t') built.Append("\\t");
                else if (ch < ' ') built.Append("\\u").Append(((int)ch).ToString("x4"));
                else built.Append(ch);
            }
            built.Append('"');
            return built.ToString();
        }

        public static bool TryParse(string body, out CompanionJson value)
        {
            value = null;
            var cursor = new JsonCursor(body);
            if (!cursor.Parse(0, out value)) return false;
            cursor.Skip();
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

            public void Skip()
            {
                while (_index < _text.Length && char.IsWhiteSpace(_text[_index])) _index++;
            }

            public bool Parse(int depth, out CompanionJson value)
            {
                value = null;
                if (depth > 32) return false;
                Skip();
                if (_index >= _text.Length) return false;
                char ch = _text[_index];
                if (ch == '{') return ParseObject(depth, out value);
                if (ch == '[') return ParseArray(depth, out value);
                if (ch == '"')
                {
                    string text;
                    if (!ParseString(out text)) return false;
                    value = CompanionJson.FromText(text);
                    return true;
                }
                if (ch == 't' || ch == 'f')
                {
                    string word = ch == 't' ? "true" : "false";
                    if (!Take(word)) return false;
                    value = CompanionJson.FromBool(ch == 't');
                    return true;
                }
                if (ch == 'n')
                {
                    if (!Take("null")) return false;
                    value = new CompanionJson();
                    return true;
                }
                if (ch == '-' || (ch >= '0' && ch <= '9')) return ParseNumber(out value);
                return false;
            }

            bool ParseObject(int depth, out CompanionJson value)
            {
                value = null;
                _index++;
                var map = new Dictionary<string, CompanionJson>(StringComparer.Ordinal);
                Skip();
                if (Eat('}'))
                {
                    value = CompanionJson.FromObject(map);
                    return true;
                }
                while (true)
                {
                    Skip();
                    string key;
                    if (!ParseString(out key)) return false;
                    if (map.ContainsKey(key)) return false;
                    Skip();
                    if (!Eat(':')) return false;
                    CompanionJson child;
                    if (!Parse(depth + 1, out child)) return false;
                    map[key] = child;
                    Skip();
                    if (Eat('}'))
                    {
                        value = CompanionJson.FromObject(map);
                        return true;
                    }
                    if (!Eat(',')) return false;
                }
            }

            bool ParseArray(int depth, out CompanionJson value)
            {
                value = null;
                _index++;
                var list = new List<CompanionJson>();
                Skip();
                if (Eat(']'))
                {
                    value = CompanionJson.FromArray(list);
                    return true;
                }
                while (true)
                {
                    CompanionJson child;
                    if (!Parse(depth + 1, out child)) return false;
                    list.Add(child);
                    Skip();
                    if (Eat(']'))
                    {
                        value = CompanionJson.FromArray(list);
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
                        else if (escaped == 'n') built.Append('\n');
                        else if (escaped == 'r') built.Append('\r');
                        else if (escaped == 't') built.Append('\t');
                        else return false;
                    }
                    else if (ch < ' ') return false;
                    else built.Append(ch);
                }
                return false;
            }

            bool ParseNumber(out CompanionJson value)
            {
                value = null;
                int start = _index;
                if (_text[_index] == '-') _index++;
                if (_index >= _text.Length || _text[_index] < '0' || _text[_index] > '9') return false;
                while (_index < _text.Length && _text[_index] >= '0' && _text[_index] <= '9') _index++;
                if (_index == start || (_text[start] == '-' && _index == start + 1)) return false;
                value = CompanionJson.FromNumber(_text.Substring(start, _index - start));
                return true;
            }

            bool Take(string word)
            {
                if (_index + word.Length > _text.Length) return false;
                if (string.CompareOrdinal(_text, _index, word, 0, word.Length) != 0) return false;
                _index += word.Length;
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

    public sealed class CompanionJson
    {
        public string Text = "";
        public bool IsText;
        public bool IsNumber;
        public string Number = "";
        public bool IsBool;
        public bool Bool;
        public List<CompanionJson> Items;
        public Dictionary<string, CompanionJson> Map;

        public static CompanionJson FromText(string text)
        {
            var value = new CompanionJson();
            value.IsText = true;
            value.Text = text ?? "";
            return value;
        }

        public static CompanionJson FromNumber(string number)
        {
            var value = new CompanionJson();
            value.IsNumber = true;
            value.Number = number ?? "";
            return value;
        }

        public static CompanionJson FromBool(bool bit)
        {
            var value = new CompanionJson();
            value.IsBool = true;
            value.Bool = bit;
            return value;
        }

        public static CompanionJson FromObject(Dictionary<string, CompanionJson> map)
        {
            var value = new CompanionJson();
            value.Map = map;
            return value;
        }

        public static CompanionJson FromArray(List<CompanionJson> items)
        {
            var value = new CompanionJson();
            value.Items = items;
            return value;
        }

        public string String(string key)
        {
            CompanionJson child;
            if (Map == null || !Map.TryGetValue(key, out child) || child == null || !child.IsText) return "";
            return child.Text ?? "";
        }

        public int Int(string key, int missing)
        {
            CompanionJson child;
            if (Map == null || !Map.TryGetValue(key, out child) || child == null || !child.IsNumber) return missing;
            int parsed;
            if (!int.TryParse(child.Number, out parsed)) return missing;
            return parsed;
        }

        public bool OkTrue()
        {
            CompanionJson child;
            if (Map == null || !Map.TryGetValue("ok", out child) || child == null || !child.IsBool) return false;
            return child.Bool;
        }
    }
}
