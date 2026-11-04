using System;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;

namespace Ironkeep.Companion
{
    /// <summary>
    /// Startup notes for the signed-in Windows user. Token text is removed before it is written.
    /// </summary>
    public static class StartupLog
    {
        static readonly object Gate = new object();
        static readonly Regex Secret = new Regex(
            @"\bik[arn]\.[A-Za-z0-9._~+/=-]{8,}|dpapi:[A-Za-z0-9+/=]+|(?i)bearer\s+\S+",
            RegexOptions.Compiled);

        public static string DirectoryOverride;

        public static string DirectoryPath()
        {
            if (DirectoryOverride != null && DirectoryOverride.Length > 0) return DirectoryOverride;
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Ironkeep", "Logs");
        }

        public static string FilePath()
        {
            return Path.Combine(DirectoryPath(), "startup.log");
        }

        public static string Redact(string text)
        {
            if (text == null || text.Length == 0) return "";
            return Secret.Replace(text, "[redacted]");
        }

        public static void Write(string step)
        {
            Append(Redact(step ?? ""));
        }

        public static void WriteException(string step, Exception error)
        {
            var built = new StringBuilder();
            built.Append(step ?? "fatal");
            Exception current = error;
            while (current != null)
            {
                built.AppendLine();
                built.Append(current.GetType().FullName);
                built.Append(": ");
                built.Append(current.Message);
                if (current.StackTrace != null && current.StackTrace.Length > 0)
                {
                    built.AppendLine();
                    built.Append(current.StackTrace);
                }
                current = current.InnerException;
            }
            Append(Redact(built.ToString()));
        }

        static void Append(string text)
        {
            try
            {
                lock (Gate)
                {
                    string directory = DirectoryPath();
                    Directory.CreateDirectory(directory);
                    string line = DateTime.UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss.fffffff'Z'", System.Globalization.CultureInfo.InvariantCulture)
                        + " " + (text ?? "").Replace("\r", " ").Replace("\n", " | ");
                    File.AppendAllText(Path.Combine(directory, "startup.log"), line + Environment.NewLine, new UTF8Encoding(false));
                }
            }
            catch (Exception)
            {
            }
        }
    }
}
