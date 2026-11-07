using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace Ironkeep
{
    /// <summary>
    /// Canonical roster JSON shared with the backend. Members are ordered by GUID.
    /// </summary>
    public static class RosterPayload
    {
        public const string Kind = "roster";

        public static string Canonical(string lua)
        {
            Dictionary<object, object> root;
            try
            {
                root = Saved.LoadNamed(lua, "IronkeepRosterDB");
            }
            catch (SavedException)
            {
                return null;
            }
            object schema = Saved.Get(root, "schema");
            if (!(schema is long) || (long)schema != 1) return null;
            string guild = Saved.Get(root, "wowGuildName") as string;
            if (guild == null) return null;
            guild = guild.Trim();
            if (guild.Length == 0 || guild.Length > 64) return null;
            object captured = Saved.Get(root, "capturedAt");
            if (!(captured is long) || (long)captured < 0) return null;
            object completeness = Saved.Get(root, "completeness");
            Dictionary<object, object> complete = completeness as Dictionary<object, object>;
            if (complete == null) return null;
            if (!string.Equals(Saved.Get(complete, "status") as string, "complete", StringComparison.Ordinal)) return null;
            object reported = Saved.Get(complete, "reportedTotal");
            object populated = Saved.Get(complete, "populated");
            if (!(reported is long) || !(populated is long)) return null;
            List<Dictionary<object, object>> members = Members(Saved.Get(root, "members"));
            if (members == null || members.Count == 0 || members.Count > 500) return null;
            if ((long)reported != members.Count || (long)populated != members.Count) return null;
            var rows = new List<Member>();
            var guids = new HashSet<string>();
            var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            for (int i = 0; i < members.Count; i++)
            {
                Member row;
                if (!TryMember(members[i], out row)) return null;
                if (!guids.Add(row.Guid) || !names.Add(row.Name)) return null;
                rows.Add(row);
            }
            rows.Sort(delegate(Member a, Member b) { return string.CompareOrdinal(a.Guid, b.Guid); });
            return Write(guild, (long)captured, rows);
        }

        public static string StatusForCount(int count)
        {
            if (count > 1)
                return "More than one IronkeepRoster.lua was found. Roster upload is paused until one account folder is selected.";
            if (count == 1) return "1 IronkeepRoster.lua file found.";
            return "No IronkeepRoster.lua found.";
        }

        static List<Dictionary<object, object>> Members(object value)
        {
            Dictionary<object, object> table = value as Dictionary<object, object>;
            if (table == null) return null;
            var rows = new List<Dictionary<object, object>>();
            for (int index = 1; ; index++)
            {
                object row;
                if (!table.TryGetValue(index, out row) && !table.TryGetValue((long)index, out row)) break;
                Dictionary<object, object> member = row as Dictionary<object, object>;
                if (member == null) return null;
                rows.Add(member);
            }
            if (rows.Count != table.Count) return null;
            return rows;
        }

        static bool TryMember(Dictionary<object, object> member, out Member row)
        {
            row = null;
            string guid = Saved.Get(member, "guid") as string;
            string name = Saved.Get(member, "name") as string;
            object level = Saved.Get(member, "level");
            string token = Saved.Get(member, "classToken") as string;
            string className = Saved.Get(member, "className") as string;
            string rank = Saved.Get(member, "rankName") as string;
            if (guid == null || name == null || token == null || className == null || rank == null) return false;
            if (!(level is long) || (long)level < 0 || (long)level > 999) return false;
            if (guid.Length == 0 || guid.Length > 64 || name.Length == 0 || name.Length > 48) return false;
            row = new Member();
            row.Guid = guid;
            row.Name = name;
            row.Level = (long)level;
            row.ClassToken = token;
            row.ClassName = className;
            row.RankName = rank;
            return true;
        }

        static string Write(string guild, long capturedAt, List<Member> rows)
        {
            var builder = new StringBuilder();
            builder.Append("{\"capturedAt\":");
            builder.Append(capturedAt.ToString(CultureInfo.InvariantCulture));
            builder.Append(",\"members\":[");
            for (int i = 0; i < rows.Count; i++)
            {
                if (i > 0) builder.Append(',');
                Member row = rows[i];
                builder.Append("{\"className\":");
                Quote(builder, row.ClassName);
                builder.Append(",\"classToken\":");
                Quote(builder, row.ClassToken);
                builder.Append(",\"guid\":");
                Quote(builder, row.Guid);
                builder.Append(",\"level\":");
                builder.Append(row.Level.ToString(CultureInfo.InvariantCulture));
                builder.Append(",\"name\":");
                Quote(builder, row.Name);
                builder.Append(",\"rankName\":");
                Quote(builder, row.RankName);
                builder.Append('}');
            }
            builder.Append("],\"schema\":1,\"wowGuildName\":");
            Quote(builder, guild);
            builder.Append('}');
            return builder.ToString();
        }

        static void Quote(StringBuilder builder, string value)
        {
            builder.Append('"');
            for (int i = 0; i < value.Length; i++)
            {
                char c = value[i];
                if (c == '"' || c == '\\')
                {
                    builder.Append('\\');
                    builder.Append(c);
                }
                else if (c == '\n') builder.Append("\\n");
                else if (c == '\r') builder.Append("\\r");
                else if (c < 0x20 || c > 0x7e)
                {
                    builder.Append("\\u");
                    builder.Append(((int)c).ToString("x4", CultureInfo.InvariantCulture));
                }
                else builder.Append(c);
            }
            builder.Append('"');
        }

        sealed class Member
        {
            public string Guid;
            public string Name;
            public long Level;
            public string ClassToken;
            public string ClassName;
            public string RankName;
        }
    }
}
