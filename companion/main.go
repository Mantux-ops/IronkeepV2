// IronkeepCompanion reads the group list the addon saved on this computer.
//
//	GOOS=windows GOARCH=amd64 go build -ldflags "-s -w" -o IronkeepCompanion.exe .
package main

import (
	_ "embed"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

//go:embed sample-Ironkeep.lua
var sampleLua string

func main() {
	code := run(os.Args[1:], os.Stdout, os.Stderr)
	if len(os.Args) == 1 {
		fmt.Fprintln(os.Stderr, "")
		fmt.Fprintln(os.Stderr, "Press Enter to close.")
		fmt.Fscanln(os.Stdin)
	}
	os.Exit(code)
}

func run(args []string, stdout, stderr io.Writer) int {
	path, db, err := open(args)
	if err != nil {
		fmt.Fprintln(stderr, err.Error())
		if len(args) == 0 {
			fmt.Fprintln(stderr, "")
			fmt.Fprintln(stderr, usage())
		}
		return 1
	}
	if db == nil {
		fmt.Fprintln(stderr, usage())
		return 2
	}
	if account := accountName(path); account != "" && len(args) > 0 && args[0] == "--wow" {
		fmt.Fprintf(stderr, "Account: %s\n", account)
	}
	if len(args) == 0 {
		if account := accountName(path); account != "" {
			fmt.Fprintf(stderr, "Account: %s\n", account)
		}
	}
	fmt.Fprintf(stderr, "Read from: %s\n", path)
	fmt.Fprintln(stdout, textFor(db))
	return 0
}

func open(args []string) (string, map[any]any, error) {
	switch {
	case len(args) == 0:
		for _, folder := range defaultWowFolders() {
			files, err := savedFiles(folder)
			if err != nil || len(files) == 0 {
				continue
			}
			path, err := newest(files)
			if err != nil {
				return "", nil, err
			}
			db, err := loadPath(path)
			return path, db, err
		}
		return "", nil, SavedError{Message: "No Ironkeep.lua yet. Log out of WoW once so the addon can write it."}
	case len(args) == 1 && args[0] == "--sample":
		db, err := loadSaved(sampleLua)
		return "built-in sample", db, err
	case len(args) == 2 && args[0] == "--file":
		db, err := loadPath(args[1])
		return args[1], db, err
	case len(args) == 2 && args[0] == "--wow":
		files, err := savedFiles(args[1])
		if err != nil {
			return "", nil, err
		}
		if len(files) == 0 {
			return "", nil, savedf("No Ironkeep.lua under %s. Log out once so the addon can write it.", args[1])
		}
		path, err := newest(files)
		if err != nil {
			return "", nil, err
		}
		db, err := loadPath(path)
		return path, db, err
	case len(args) == 1 && !strings.HasPrefix(args[0], "-"):
		db, err := loadPath(args[0])
		return args[0], db, err
	default:
		return "", nil, nil
	}
}

func defaultWowFolders() []string {
	return []string{
		`G:\World of Warcraft\_forever_`,
		`C:\World of Warcraft\_forever_`,
	}
}

func accountName(path string) string {
	if path == "" || path == "built-in sample" {
		return ""
	}
	return filepath.Base(filepath.Dir(filepath.Dir(path)))
}

func usage() string {
	return strings.TrimSpace(`
IronkeepCompanion reads the group list saved by the WoW: Forever addon.

  IronkeepCompanion.exe
  IronkeepCompanion.exe --wow "G:\World of Warcraft\_forever_"
  IronkeepCompanion.exe --file "G:\World of Warcraft\_forever_\WTF\Account\NAME\SavedVariables\Ironkeep.lua"
  IronkeepCompanion.exe --sample

With no arguments it looks in G:\World of Warcraft\_forever_ and then C:\World of Warcraft\_forever_.
The addon writes the file when you log out or /reload. Nothing is sent to the site.
`)
}
