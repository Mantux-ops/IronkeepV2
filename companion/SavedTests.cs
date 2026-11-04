using System;
using System.Collections.Generic;
using System.IO;

namespace Ironkeep
{
    static class SavedTests
    {
        static int failures;

        static void Main()
        {
            SampleMatchesTheCopyList();
            PreviousReportIsKeptWhenTheSessionWasCleared();
            ACallInTheFileIsRefused();
            MissingListIsRefused();
            NewestAccountFileIsChosen();
            EveryAccountFileIsListed();
            SampleCommandPrintsTheGroup();
            DescribeSampleHasThreePeople();
            APlaintextKeyIsRewrittenProtected();
            EachAccountIsRememberedOnItsOwn();
            AFileIsReadAfterItsSizeSettles();
            RetriesBackOffAndThenStop();
            WindowsProtectsTheKeyForThisUser();
            if (failures > 0)
            {
                Console.Error.WriteLine(failures + " failed");
                Environment.Exit(1);
            }
            Console.WriteLine("ok");
        }

        static void Check(bool condition, string name)
        {
            if (condition) return;
            failures++;
            Console.Error.WriteLine("FAIL " + name);
        }

        static void SampleMatchesTheCopyList()
        {
            var db = Saved.LoadPath("sample-Ironkeep.lua");
            string text = Saved.Report((Dictionary<object, object>)db["session"], "2026-11-01 12:00");
            string want = string.Join("\n", new string[] {
                "Ironkeep group",
                "Place: Hall of Thanes",
                "Started: 2026-11-01 12:00",
                "",
                "Name | Class | Role | Time | Status",
                "Ada Smith | Warrior | Tank | 20m | here",
                "Bram Holt | Priest | Healer | 10m | here",
                "Dain Frost | Mage | Damage | 5m | left",
                "",
                "format: ironkeep-group 1"
            });
            Check(text == want, "sample report\n" + text);
        }

        static void PreviousReportIsKeptWhenTheSessionWasCleared()
        {
            var db = Saved.Load("IronkeepDB = { [\"lastReport\"] = \"Ironkeep group\\n\\nformat: ironkeep-group 1\" }\n");
            Check(Saved.TextFor(db) == "Ironkeep group\n\nformat: ironkeep-group 1", "previous report");
            Check(Saved.Describe(db).Previous && Saved.Describe(db).People.Count == 0, "previous flag");
        }

        static void ACallInTheFileIsRefused()
        {
            bool refused = false;
            try { Saved.Load("IronkeepDB = { [\"session\"] = os.execute(\"rm\") }\n"); }
            catch (SavedException) { refused = true; }
            Check(refused, "call refused");
        }

        static void MissingListIsRefused()
        {
            bool refused = false;
            try { Saved.Load("SomethingElse = {}\n"); }
            catch (SavedException) { refused = true; }
            Check(refused, "missing list");
        }

        static void NewestAccountFileIsChosen()
        {
            string wow = Path.Combine(Path.GetTempPath(), "ironkeep-companion-" + Guid.NewGuid().ToString("N"));
            string older = Path.Combine(wow, "WTF", "Account", "Old", "SavedVariables", "Ironkeep.lua");
            string newer = Path.Combine(wow, "WTF", "Account", "New", "SavedVariables", "Ironkeep.lua");
            Directory.CreateDirectory(Path.GetDirectoryName(older));
            Directory.CreateDirectory(Path.GetDirectoryName(newer));
            File.Copy("sample-Ironkeep.lua", older);
            File.Copy("sample-Ironkeep.lua", newer);
            File.SetLastWriteTimeUtc(older, new DateTime(2000, 1, 1, 0, 0, 0, DateTimeKind.Utc));
            File.SetLastWriteTimeUtc(newer, new DateTime(2000, 1, 2, 0, 0, 0, DateTimeKind.Utc));
            Check(Saved.Newest(Saved.SavedFiles(wow)) == newer, "newest file");
            Check(Saved.FindSaved(wow) == newer, "find under wow");
            Check(Saved.FindSaved(newer) == newer, "find file");
            Check(Saved.FindSaved(Path.GetDirectoryName(newer)) == newer, "find savedvariables");
            string wtf = Path.Combine(wow, "WTF");
            Check(Saved.FindSaved(wtf) == newer, "find wtf");
            var stdout = new StringWriter();
            var stderr = new StringWriter();
            int code = Program.Run(new string[] { "--wow", wow }, stdout, stderr);
            Check(code == 0, "wow exit " + stderr);
            Check(stderr.ToString().Contains("Account: New"), "account name\n" + stderr);
            Check(stdout.ToString().Contains("Ada Smith | Warrior | Tank | 20m | here"), "tank line");
            Check(stdout.ToString().Contains("format: ironkeep-group 1"), "format line");
            Directory.Delete(wow, true);
        }

        static void SampleCommandPrintsTheGroup()
        {
            var stdout = new StringWriter();
            var stderr = new StringWriter();
            int code = Program.Run(new string[] { "--sample" }, stdout, stderr);
            Check(code == 0, "sample exit " + stderr);
            Check(stdout.ToString().Contains("Hall of Thanes"), "place");
            Check(stdout.ToString().Contains("Dain Frost | Mage | Damage | 5m | left"), "left");
        }

        static void DescribeSampleHasThreePeople()
        {
            GroupList group = Saved.Describe(Saved.LoadPath("sample-Ironkeep.lua"));
            Check(group.People.Count == 3, "count " + group.People.Count);
            Check(!group.Previous, "not previous");
            Check(group.Place == "Hall of Thanes", "place " + group.Place);
            Check(group.People[0].Name == "Ada Smith" && group.People[0].Here && group.People[0].ClassFile == "WARRIOR", "ada");
            Check(group.People[1].Name == "Bram Holt" && group.People[1].Role == "Healer", "bram");
            Check(group.People[2].Name == "Dain Frost" && !group.People[2].Here && group.People[2].Role == "Damage", "dain");
            Check(group.Text.Contains("format: ironkeep-group 1"), "text");
            Check(Saved.Describe(Saved.Load(Saved.EmbeddedSample())).Place == "Hall of Thanes", "embedded");
        }

        static void EveryAccountFileIsListed()
        {
            string wow = Path.Combine(Path.GetTempPath(), "ironkeep-companion-" + Guid.NewGuid().ToString("N"));
            string older = Path.Combine(wow, "WTF", "Account", "Old", "SavedVariables", "Ironkeep.lua");
            string newer = Path.Combine(wow, "WTF", "Account", "New", "SavedVariables", "Ironkeep.lua");
            Directory.CreateDirectory(Path.GetDirectoryName(older));
            Directory.CreateDirectory(Path.GetDirectoryName(newer));
            File.WriteAllText(older, "IronkeepDB = {}\n");
            File.WriteAllText(newer, "IronkeepDB = {}\n");
            var files = Saved.AllSaved(wow);
            Check(files.Count == 2, "both accounts " + files.Count);
            Check(files.Contains(older) && files.Contains(newer), "both paths");
            Check(Saved.AllSaved(Path.Combine(wow, "WTF")).Count == 2, "both under wtf");
            Directory.Delete(wow, true);
        }

        static void APlaintextKeyIsRewrittenProtected()
        {
            string dir = Path.Combine(Path.GetTempPath(), "ironkeep-companion-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(dir);
            string file = Path.Combine(dir, "companion-site.txt");
            File.WriteAllLines(file, new string[] { "https://ironkeep.gg", "my-guild", "secret-token" });
            var store = new SiteStore(file, new PrefixProtector());
            SiteSettings site = store.Load();
            Check(site.Token == "secret-token", "migrated token");
            Check(site.Slug == "my-guild", "migrated guild");
            string stored = File.ReadAllText(file);
            Check(stored.IndexOf("secret-token") < 0, "plaintext removed\n" + stored);
            Check(stored.IndexOf("test:") >= 0, "protected prefix");
            SiteSettings again = store.Load();
            Check(again.Token == "secret-token" && !again.Unreadable, "read back");
            Directory.Delete(dir, true);
        }

        static void EachAccountIsRememberedOnItsOwn()
        {
            string dir = Path.Combine(Path.GetTempPath(), "ironkeep-companion-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(dir);
            var ledger = new SendLedger(Path.Combine(dir, "companion-sent.txt"));
            string one = Path.Combine(dir, "One", "Ironkeep.lua");
            string two = Path.Combine(dir, "Two", "Ironkeep.lua");
            ledger.Remember(one, "aaa");
            Check(ledger.Has(one, "aaa"), "first remembered");
            Check(!ledger.Has(two, "aaa"), "second still open");
            var again = new SendLedger(Path.Combine(dir, "companion-sent.txt"));
            Check(again.Has(one, "aaa"), "reloaded");
            Check(!again.Has(one, "bbb"), "changed report");
            Directory.Delete(dir, true);
        }

        static void AFileIsReadAfterItsSizeSettles()
        {
            var watch = new SettleWatch();
            Check(!watch.Due(10), "first look waits");
            Check(!watch.Due(12), "growing file waits");
            Check(watch.Due(12), "stable size is ready");
            Check(!watch.Due(12), "the next look waits again");
            watch.Reset();
            Check(!watch.Due(-1), "missing file waits");
            Check(!watch.Due(4), "after reset the first look waits");
        }

        static void RetriesBackOffAndThenStop()
        {
            Check(SendRetry.Seconds(1) == 15, "first wait");
            Check(SendRetry.Seconds(2) == 60, "second wait");
            Check(SendRetry.Seconds(3) == 300, "third wait");
            Check(SendRetry.Seconds(4) == 0, "then stop");
            Check(SiteClient.Retryable(0) && SiteClient.Retryable(503), "offline retries");
            Check(!SiteClient.Retryable(401) && !SiteClient.Retryable(400) && !SiteClient.Retryable(413), "bad reports do not retry");
            string problem;
            Uri url = SiteClient.Target("http://127.0.0.1:8765", "my-guild", out problem);
            Check(url != null && url.AbsolutePath == "/api/my-guild/attendance", "local target " + url);
            Check(SiteClient.Target("http://example.com", "my-guild", out problem) == null, "https required");
            Check(SiteClient.Accepted("{\"ok\":true}") && SiteClient.Duplicate("{\"ok\":true,\"duplicate\":true}"), "response words");
        }

        static void WindowsProtectsTheKeyForThisUser()
        {
            if (Environment.OSVersion.Platform != PlatformID.Win32NT) return;
            if (Type.GetType("Mono.Runtime") != null) return;
            string dir = Path.Combine(Path.GetTempPath(), "ironkeep-companion-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(dir);
            string file = Path.Combine(dir, "companion-site.txt");
            var store = new SiteStore(file, new DpapiProtector());
            store.Save("https://ironkeep.gg", "my-guild", "secret-token");
            string stored = File.ReadAllText(file);
            Check(stored.IndexOf("secret-token") < 0, "dpapi hid the token\n" + stored);
            Check(stored.IndexOf("dpapi:") >= 0, "dpapi prefix");
            SiteSettings site = store.Load();
            Check(site.Token == "secret-token" && !site.Unreadable, "dpapi restore");
            Directory.Delete(dir, true);
        }
    }
}
