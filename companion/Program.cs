using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Text;

[assembly: AssemblyTitle("Ironkeep Companion")]
[assembly: AssemblyDescription("Reads the Ironkeep group list saved by the WoW: Forever addon. It does not change the game and does not send the list anywhere.")]
[assembly: AssemblyCompany("Ironkeep")]
[assembly: AssemblyProduct("Ironkeep")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]

namespace Ironkeep
{
    static class Program
    {
        static int Main(string[] args)
        {
            int code = Run(args, Console.Out, Console.Error);
            if (args.Length == 0)
            {
                Console.Error.WriteLine();
                Console.Error.WriteLine("Press Enter to close.");
                Console.ReadLine();
            }
            return code;
        }

        public static int Run(string[] args, TextWriter stdout, TextWriter stderr)
        {
            try
            {
                string path;
                Dictionary<object, object> db = Open(args, out path);
                if (db == null)
                {
                    stderr.WriteLine(Usage());
                    return 2;
                }
                string account = AccountName(path);
                if (account.Length > 0 && (args.Length == 0 || (args.Length > 0 && args[0] == "--wow")))
                    stderr.WriteLine("Account: " + account);
                stderr.WriteLine("Read from: " + path);
                stdout.WriteLine(Saved.TextFor(db));
                return 0;
            }
            catch (SavedException ex)
            {
                stderr.WriteLine(ex.Message);
                if (args.Length == 0)
                {
                    stderr.WriteLine();
                    stderr.WriteLine(Usage());
                }
                return 1;
            }
        }

        static Dictionary<object, object> Open(string[] args, out string path)
        {
            path = "";
            if (args.Length == 0)
            {
                foreach (string folder in DefaultWowFolders())
                {
                    var files = Saved.SavedFiles(folder);
                    if (files.Count == 0) continue;
                    path = Saved.Newest(files);
                    return Saved.LoadPath(path);
                }
                throw new SavedException("No Ironkeep.lua yet. Log out of WoW once so the addon can write it.");
            }
            if (args.Length == 1 && args[0] == "--sample")
            {
                path = "built-in sample";
                return Saved.Load(SampleText());
            }
            if (args.Length == 2 && args[0] == "--file")
            {
                path = args[1];
                return Saved.LoadPath(path);
            }
            if (args.Length == 2 && args[0] == "--wow")
            {
                var files = Saved.SavedFiles(args[1]);
                if (files.Count == 0)
                    throw new SavedException("No Ironkeep.lua under " + args[1] + ". Log out once so the addon can write it.");
                path = Saved.Newest(files);
                return Saved.LoadPath(path);
            }
            if (args.Length == 1 && !args[0].StartsWith("-"))
            {
                path = args[0];
                return Saved.LoadPath(path);
            }
            return null;
        }

        static string[] DefaultWowFolders()
        {
            return new string[] {
                @"G:\World of Warcraft\_forever_",
                @"C:\World of Warcraft\_forever_"
            };
        }

        static string AccountName(string path)
        {
            if (path.Length == 0 || path == "built-in sample") return "";
            string saved = Path.GetDirectoryName(path);
            string account = Path.GetDirectoryName(saved);
            return Path.GetFileName(account);
        }

        static string SampleText()
        {
            using (Stream stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("sample-Ironkeep.lua"))
            {
                if (stream == null) throw new SavedException("The built-in sample is missing.");
                using (var reader = new StreamReader(stream, Encoding.UTF8))
                    return reader.ReadToEnd();
            }
        }

        static string Usage()
        {
            return string.Join("\n", new string[] {
                "IronkeepCompanion reads the group list saved by the WoW: Forever addon.",
                "",
                "  IronkeepCompanion.exe",
                "  IronkeepCompanion.exe --wow \"G:\\World of Warcraft\\_forever_\"",
                "  IronkeepCompanion.exe --file \"G:\\World of Warcraft\\_forever_\\WTF\\Account\\NAME\\SavedVariables\\Ironkeep.lua\"",
                "  IronkeepCompanion.exe --sample",
                "",
                "With no arguments it looks in G:\\World of Warcraft\\_forever_ and then C:\\World of Warcraft\\_forever_.",
                "The addon writes the file when you log out or /reload. Nothing is sent to the site."
            });
        }
    }
}
