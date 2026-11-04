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
            SampleCommandPrintsTheGroup();
            DescribeSampleHasThreePeople();
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
    }
}
