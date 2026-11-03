package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestSampleMatchesTheCopyList(t *testing.T) {
	db, err := loadPath("sample-Ironkeep.lua")
	if err != nil {
		t.Fatal(err)
	}
	text := report(asMap(db["session"]), "2026-11-01 12:00")
	want := strings.Join([]string{
		"Ironkeep group",
		"Place: Hall of Thanes",
		"Started: 2026-11-01 12:00",
		"",
		"Name | Class | Role | Time | Status",
		"Ada Smith | Warrior | Tank | 20m | here",
		"Bram Holt | Priest | Healer | 10m | here",
		"Dain Frost | Mage | Damage | 5m | left",
		"",
		"format: ironkeep-group 1",
	}, "\n")
	if text != want {
		t.Fatalf("report\n%s", text)
	}
}

func TestPreviousReportIsKeptWhenTheSessionWasCleared(t *testing.T) {
	db, err := loadSaved("IronkeepDB = { [\"lastReport\"] = \"Ironkeep group\\n\\nformat: ironkeep-group 1\" }\n")
	if err != nil {
		t.Fatal(err)
	}
	if got := textFor(db); got != "Ironkeep group\n\nformat: ironkeep-group 1" {
		t.Fatalf("%q", got)
	}
}

func TestACallInTheFileIsRefused(t *testing.T) {
	_, err := loadSaved("IronkeepDB = { [\"session\"] = os.execute(\"rm\") }\n")
	if err == nil {
		t.Fatal("expected the call to be refused")
	}
}

func TestMissingListIsRefused(t *testing.T) {
	_, err := loadSaved("SomethingElse = {}\n")
	if err == nil {
		t.Fatal("expected a missing list to be refused")
	}
}

func TestNewestAccountFileIsChosen(t *testing.T) {
	wow := t.TempDir()
	older := filepath.Join(wow, "WTF", "Account", "Old", "SavedVariables", "Ironkeep.lua")
	newer := filepath.Join(wow, "WTF", "Account", "New", "SavedVariables", "Ironkeep.lua")
	raw, err := os.ReadFile("sample-Ironkeep.lua")
	if err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{older, newer} {
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, raw, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	oldTime := time.Unix(1_000, 0)
	newTime := time.Unix(2_000, 0)
	if err := os.Chtimes(older, oldTime, oldTime); err != nil {
		t.Fatal(err)
	}
	if err := os.Chtimes(newer, newTime, newTime); err != nil {
		t.Fatal(err)
	}
	files, err := savedFiles(wow)
	if err != nil {
		t.Fatal(err)
	}
	got, err := newest(files)
	if err != nil {
		t.Fatal(err)
	}
	if got != newer {
		t.Fatalf("newest = %s", got)
	}
	var stdout, stderr bytes.Buffer
	code := run([]string{"--wow", wow}, &stdout, &stderr)
	if code != 0 {
		t.Fatal(stderr.String())
	}
	if !strings.Contains(stderr.String(), "Account: New") {
		t.Fatalf("stderr:\n%s", stderr.String())
	}
	if !strings.Contains(stdout.String(), "Ada Smith | Warrior | Tank | 20m | here") {
		t.Fatalf("stdout:\n%s", stdout.String())
	}
	if !strings.Contains(stdout.String(), "format: ironkeep-group 1") {
		t.Fatalf("stdout:\n%s", stdout.String())
	}
}

func TestSampleCommandPrintsTheGroup(t *testing.T) {
	var stdout, stderr bytes.Buffer
	code := run([]string{"--sample"}, &stdout, &stderr)
	if code != 0 {
		t.Fatal(stderr.String())
	}
	if !strings.Contains(stdout.String(), "Hall of Thanes") || !strings.Contains(stdout.String(), "Dain Frost | Mage | Damage | 5m | left") {
		t.Fatalf("stdout:\n%s", stdout.String())
	}
}
