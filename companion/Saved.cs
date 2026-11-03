using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;

namespace Ironkeep
{
    public class SavedException : Exception
    {
        public SavedException(string message) : base(message) { }
    }

    public static class Saved
    {
        static readonly SavedException Unreadable = new SavedException("This saved file could not be read.");
        static readonly SavedException CutOff = new SavedException("This saved file is cut off.");
        static readonly Dictionary<string, int> RoleOrder = new Dictionary<string, int> {
            { "TANK", 1 }, { "HEALER", 2 }, { "DAMAGER", 3 }
        };
        static readonly Dictionary<string, string> RoleLabel = new Dictionary<string, string> {
            { "TANK", "Tank" }, { "HEALER", "Healer" }, { "DAMAGER", "Damage" }
        };

        public static Dictionary<object, object> Load(string text)
        {
            var reader = new Reader(text.TrimStart('\uFEFF'));
            var found = new Dictionary<string, object>();
            while (true)
            {
                reader.Skip();
                if (reader.End) break;
                string name = reader.Ident();
                reader.Expect("=");
                found[name] = reader.Value();
            }
            object db;
            if (!found.TryGetValue("IronkeepDB", out db) || !(db is Dictionary<object, object>))
                throw new SavedException("This file has no Ironkeep list.");
            return (Dictionary<object, object>)db;
        }

        public static Dictionary<object, object> LoadPath(string path)
        {
            string text;
            try
            {
                text = File.ReadAllText(path, Encoding.UTF8);
            }
            catch (IOException)
            {
                throw new SavedException("Could not open " + path + ".");
            }
            catch (UnauthorizedAccessException)
            {
                throw new SavedException("Could not open " + path + ".");
            }
            return Load(text);
        }

        public static List<string> SavedFiles(string wowDir)
        {
            string root = Path.Combine(wowDir, "WTF", "Account");
            var files = new List<string>();
            if (!Directory.Exists(root)) return files;
            foreach (string account in Directory.GetDirectories(root))
            {
                string path = Path.Combine(account, "SavedVariables", "Ironkeep.lua");
                if (File.Exists(path)) files.Add(path);
            }
            files.Sort(StringComparer.Ordinal);
            return files;
        }

        public static string Newest(List<string> files)
        {
            if (files == null || files.Count == 0)
                throw new SavedException("This file has no Ironkeep list.");
            string best = files[0];
            DateTime bestTime = File.GetLastWriteTimeUtc(best);
            for (int i = 1; i < files.Count; i++)
            {
                DateTime when = File.GetLastWriteTimeUtc(files[i]);
                if (when > bestTime)
                {
                    best = files[i];
                    bestTime = when;
                }
            }
            return best;
        }

        public static string TextFor(Dictionary<object, object> db)
        {
            object session;
            if (db.TryGetValue("session", out session) && session is Dictionary<object, object>)
                return Report((Dictionary<object, object>)session, null);
            object previous;
            if (db.TryGetValue("lastReport", out previous) && previous is string && ((string)previous).Trim().Length > 0)
                return (string)previous;
            return "Ironkeep group\n\nNobody recorded yet.";
        }

        public static string Report(Dictionary<object, object> session, string startedAt)
        {
            if (session == null) return "Ironkeep group\n\nNobody recorded yet.";
            if (startedAt == null)
            {
                double started;
                if (Number(Get(session, "started"), out started))
                    startedAt = Epoch.AddSeconds(started).ToLocalTime().ToString("yyyy-MM-dd HH:mm", CultureInfo.InvariantCulture);
                else
                    startedAt = "";
            }
            string place = AsString(Get(session, "place"));
            if (place.Length == 0) place = "Unknown";
            var lines = new List<string> {
                "Ironkeep group",
                "Place: " + place,
                "Started: " + startedAt,
                "",
                "Name | Class | Role | Time | Status"
            };
            var people = Rows(session);
            foreach (var person in people)
            {
                string status = Get(person, "present") is bool && (bool)Get(person, "present") ? "here" : "left";
                string name = AsString(Get(person, "name"));
                if (name.Length == 0) name = "Unknown";
                string className = AsString(Get(person, "className"));
                if (className.Length == 0) className = AsString(Get(person, "classFile"));
                string role = AsString(Get(person, "role"));
                string label;
                if (!RoleLabel.TryGetValue(role, out label)) label = "";
                lines.Add(string.Join(" | ", new string[] { name, className, label, Seen(person), status }));
            }
            if (people.Count == 0) lines.Add("Nobody recorded yet.");
            lines.Add("");
            lines.Add("format: ironkeep-group 1");
            return string.Join("\n", lines.ToArray());
        }

        static readonly DateTime Epoch = new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc);

        static List<Dictionary<object, object>> Rows(Dictionary<object, object> session)
        {
            var list = new List<Dictionary<object, object>>();
            object people = Get(session, "people");
            var table = people as Dictionary<object, object>;
            if (table != null)
            {
                foreach (object value in table.Values)
                {
                    var person = value as Dictionary<object, object>;
                    if (person != null) list.Add(person);
                }
            }
            list.Sort(ComparePeople);
            return list;
        }

        static int ComparePeople(Dictionary<object, object> a, Dictionary<object, object> b)
        {
            int aPresent = Get(a, "present") is bool && (bool)Get(a, "present") ? 0 : 1;
            int bPresent = Get(b, "present") is bool && (bool)Get(b, "present") ? 0 : 1;
            if (aPresent != bPresent) return aPresent - bPresent;
            double aGroup, bGroup;
            if (!Number(Get(a, "subgroup"), out aGroup)) aGroup = 99;
            if (!Number(Get(b, "subgroup"), out bGroup)) bGroup = 99;
            if (aGroup != bGroup) return aGroup < bGroup ? -1 : 1;
            int aRole, bRole;
            if (!RoleOrder.TryGetValue(AsString(Get(a, "role")), out aRole)) aRole = 9;
            if (!RoleOrder.TryGetValue(AsString(Get(b, "role")), out bRole)) bRole = 9;
            if (aRole != bRole) return aRole - bRole;
            return string.CompareOrdinal(AsString(Get(a, "name")), AsString(Get(b, "name")));
        }

        static string Seen(Dictionary<object, object> person)
        {
            double first, last;
            if (!Number(Get(person, "first"), out first) || !Number(Get(person, "last"), out last))
                return "";
            int minutes = (int)Math.Floor((last - first) / 60.0);
            if (minutes < 1) return "<1m";
            if (minutes < 60) return minutes.ToString(CultureInfo.InvariantCulture) + "m";
            return (minutes / 60).ToString(CultureInfo.InvariantCulture) + "h " + (minutes % 60).ToString(CultureInfo.InvariantCulture) + "m";
        }

        public static object Get(Dictionary<object, object> table, string key)
        {
            object value;
            if (table != null && table.TryGetValue(key, out value)) return value;
            return null;
        }

        static string AsString(object value)
        {
            return value as string ?? "";
        }

        static bool Number(object value, out double number)
        {
            if (value is long)
            {
                number = (long)value;
                return true;
            }
            if (value is double)
            {
                number = (double)value;
                return true;
            }
            number = 0;
            return false;
        }

        sealed class Reader
        {
            readonly string text;
            int i;

            public Reader(string text) { this.text = text ?? ""; }

            public bool End { get { return i >= text.Length; } }

            char Peek() { return i < text.Length ? text[i] : '\0'; }

            bool Starts(string token)
            {
                return string.CompareOrdinal(text, i, token, 0, token.Length) == 0;
            }

            public void Skip()
            {
                while (i < text.Length)
                {
                    char c = text[i];
                    if (c == ' ' || c == '\t' || c == '\r' || c == '\n') { i++; continue; }
                    if (Starts("--"))
                    {
                        i += 2;
                        if (Starts("["))
                        {
                            int mark = i;
                            i++;
                            int equals = 0;
                            while (Peek() == '=') { equals++; i++; }
                            if (Peek() == '[')
                            {
                                i++;
                                string close = "]" + new string('=', equals) + "]";
                                int end = text.IndexOf(close, i, StringComparison.Ordinal);
                                if (end < 0) throw CutOff;
                                i = end + close.Length;
                                continue;
                            }
                            i = mark;
                        }
                        int line = text.IndexOf('\n', i);
                        i = line < 0 ? text.Length : line + 1;
                        continue;
                    }
                    return;
                }
            }

            public void Expect(string token)
            {
                Skip();
                if (!Starts(token)) throw Unreadable;
                i += token.Length;
            }

            bool Eat(string token)
            {
                Skip();
                if (!Starts(token)) return false;
                i += token.Length;
                return true;
            }

            public string Ident()
            {
                Skip();
                int start = i;
                if (!IsIdentStart(Peek())) throw Unreadable;
                i++;
                while (IsIdentPart(Peek())) i++;
                return text.Substring(start, i - start);
            }

            static bool IsIdentStart(char c) { return char.IsLetter(c) || c == '_'; }
            static bool IsIdentPart(char c) { return char.IsLetterOrDigit(c) || c == '_'; }

            public object Value()
            {
                Skip();
                char c = Peek();
                if (c == '{') return Table();
                if (c == '"' || c == '\'') return Quote();
                if (c == '[') return LongString();
                if (c == '-' || char.IsDigit(c)) return Number();
                if (IsIdentStart(c))
                {
                    string word = Ident();
                    if (word == "true") return true;
                    if (word == "false") return false;
                    if (word == "nil") return null;
                    throw Unreadable;
                }
                throw Unreadable;
            }

            Dictionary<object, object> Table()
            {
                Expect("{");
                var data = new Dictionary<object, object>();
                int index = 1;
                while (true)
                {
                    Skip();
                    if (Eat("}")) return data;
                    if (Eat("["))
                    {
                        object key = Value();
                        Expect("]");
                        Expect("=");
                        data[key] = Value();
                    }
                    else if (IsIdentStart(Peek()))
                    {
                        int mark = i;
                        string name = Ident();
                        if (Eat("=")) data[name] = Value();
                        else
                        {
                            i = mark;
                            data[index] = Value();
                            index++;
                        }
                    }
                    else
                    {
                        data[index] = Value();
                        index++;
                    }
                    Skip();
                    Eat(",");
                    Eat(";");
                }
            }

            string Quote()
            {
                char quote = Peek();
                i++;
                var chars = new StringBuilder();
                while (i < text.Length)
                {
                    char c = text[i];
                    if (c == quote) { i++; return chars.ToString(); }
                    if (c == '\\') { chars.Append(Escape()); continue; }
                    if (c == '\n') throw Unreadable;
                    chars.Append(c);
                    i++;
                }
                throw CutOff;
            }

            string Escape()
            {
                i++;
                if (i >= text.Length) throw CutOff;
                char c = text[i++];
                switch (c)
                {
                    case 'a': return "\a";
                    case 'b': return "\b";
                    case 'f': return "\f";
                    case 'n': return "\n";
                    case 'r': return "\r";
                    case 't': return "\t";
                    case 'v': return "\v";
                    case '\\':
                    case '"':
                    case '\'': return c.ToString();
                    case '\n': return "\n";
                }
                if (c >= '0' && c <= '9')
                {
                    string digits = c.ToString();
                    for (int n = 0; n < 2 && i < text.Length && text[i] >= '0' && text[i] <= '9'; n++)
                        digits += text[i++];
                    int code = int.Parse(digits, CultureInfo.InvariantCulture);
                    if (code > 255) throw Unreadable;
                    return ((char)code).ToString();
                }
                throw Unreadable;
            }

            string LongString()
            {
                Expect("[");
                int equals = 0;
                while (Eat("=")) equals++;
                Expect("[");
                if (Peek() == '\n') i++;
                string close = "]" + new string('=', equals) + "]";
                int end = text.IndexOf(close, i, StringComparison.Ordinal);
                if (end < 0) throw CutOff;
                string value = text.Substring(i, end - i);
                i = end + close.Length;
                return value;
            }

            object Number()
            {
                int start = i;
                if (Peek() == '-') i++;
                bool saw = false;
                while (char.IsDigit(Peek())) { saw = true; i++; }
                bool floating = false;
                if (Peek() == '.')
                {
                    floating = true;
                    i++;
                    while (char.IsDigit(Peek())) { saw = true; i++; }
                }
                if (!saw) throw Unreadable;
                string token = text.Substring(start, i - start);
                if (floating) return double.Parse(token, CultureInfo.InvariantCulture);
                return long.Parse(token, CultureInfo.InvariantCulture);
            }
        }
    }
}
