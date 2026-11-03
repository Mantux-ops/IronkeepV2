package main

import (
	"fmt"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

// SavedError means the file is missing, unreadable, or not an Ironkeep list.
type SavedError struct{ Message string }

func (e SavedError) Error() string { return e.Message }

func savedf(format string, args ...any) error {
	return SavedError{Message: fmt.Sprintf(format, args...)}
}

var (
	errRead = SavedError{Message: "This saved file could not be read."}
	errCut  = SavedError{Message: "This saved file is cut off."}
	errNoDB = SavedError{Message: "This file has no Ironkeep list."}
)

type reader struct {
	text string
	n    int
	i    int
}

func loadSaved(text string) (map[any]any, error) {
	r := &reader{text: strings.TrimPrefix(text, "\uFEFF")}
	r.n = len(r.text)
	found := map[string]any{}
	for {
		r.skip()
		if r.i >= r.n {
			break
		}
		name, err := r.ident()
		if err != nil {
			return nil, err
		}
		if err := r.expect("="); err != nil {
			return nil, err
		}
		value, err := r.value()
		if err != nil {
			return nil, err
		}
		found[name] = value
	}
	db, ok := found["IronkeepDB"].(map[any]any)
	if !ok {
		return nil, errNoDB
	}
	return db, nil
}

func loadPath(path string) (map[any]any, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, savedf("Could not open %s.", path)
	}
	if !utf8.Valid(raw) {
		return nil, savedf("Could not read %s.", path)
	}
	return loadSaved(string(raw))
}

func (r *reader) peek() byte {
	if r.i >= r.n {
		return 0
	}
	return r.text[r.i]
}

func (r *reader) starts(token string) bool {
	return strings.HasPrefix(r.text[r.i:], token)
}

func (r *reader) skip() {
	for r.i < r.n {
		switch r.text[r.i] {
		case ' ', '\t', '\r', '\n':
			r.i++
			continue
		}
		if r.starts("--") {
			r.i += 2
			if r.starts("[") {
				mark := r.i
				r.i++
				equals := 0
				for r.peek() == '=' {
					equals++
					r.i++
				}
				if r.peek() == '[' {
					r.i++
					close := "]" + strings.Repeat("=", equals) + "]"
					end := strings.Index(r.text[r.i:], close)
					if end < 0 {
						r.i = r.n
						return
					}
					r.i += end + len(close)
					continue
				}
				r.i = mark
			}
			end := strings.IndexByte(r.text[r.i:], '\n')
			if end < 0 {
				r.i = r.n
			} else {
				r.i += end + 1
			}
			continue
		}
		return
	}
}

func (r *reader) expect(token string) error {
	r.skip()
	if !r.starts(token) {
		return errRead
	}
	r.i += len(token)
	return nil
}

func (r *reader) eat(token string) bool {
	r.skip()
	if r.starts(token) {
		r.i += len(token)
		return true
	}
	return false
}

func (r *reader) ident() (string, error) {
	r.skip()
	start := r.i
	if r.i >= r.n {
		return "", errRead
	}
	ch, _ := utf8.DecodeRuneInString(r.text[r.i:])
	if !unicode.IsLetter(ch) && ch != '_' {
		return "", errRead
	}
	r.i += utf8.RuneLen(ch)
	for r.i < r.n {
		ch, size := utf8.DecodeRuneInString(r.text[r.i:])
		if !unicode.IsLetter(ch) && !unicode.IsDigit(ch) && ch != '_' {
			break
		}
		r.i += size
	}
	return r.text[start:r.i], nil
}

func (r *reader) value() (any, error) {
	r.skip()
	if r.i >= r.n {
		return nil, errRead
	}
	switch r.peek() {
	case '{':
		return r.table()
	case '"', '\'':
		return r.quote()
	case '[':
		return r.longString()
	}
	if r.peek() == '-' || (r.peek() >= '0' && r.peek() <= '9') {
		return r.number()
	}
	ch, _ := utf8.DecodeRuneInString(r.text[r.i:])
	if unicode.IsLetter(ch) || ch == '_' {
		word, err := r.ident()
		if err != nil {
			return nil, err
		}
		switch word {
		case "true":
			return true, nil
		case "false":
			return false, nil
		case "nil":
			return nil, nil
		default:
			return nil, errRead
		}
	}
	return nil, errRead
}

func (r *reader) table() (map[any]any, error) {
	if err := r.expect("{"); err != nil {
		return nil, err
	}
	data := map[any]any{}
	index := 1
	for {
		r.skip()
		if r.eat("}") {
			return data, nil
		}
		if r.eat("[") {
			key, err := r.value()
			if err != nil {
				return nil, err
			}
			if err := r.expect("]"); err != nil {
				return nil, err
			}
			if err := r.expect("="); err != nil {
				return nil, err
			}
			value, err := r.value()
			if err != nil {
				return nil, err
			}
			data[key] = value
		} else {
			mark := r.i
			ch, _ := utf8.DecodeRuneInString(r.text[r.i:])
			if unicode.IsLetter(ch) || ch == '_' {
				name, err := r.ident()
				if err != nil {
					return nil, err
				}
				if r.eat("=") {
					value, err := r.value()
					if err != nil {
						return nil, err
					}
					data[name] = value
				} else {
					r.i = mark
					value, err := r.value()
					if err != nil {
						return nil, err
					}
					data[index] = value
					index++
				}
			} else {
				value, err := r.value()
				if err != nil {
					return nil, err
				}
				data[index] = value
				index++
			}
		}
		r.skip()
		r.eat(",")
		r.eat(";")
	}
}

func (r *reader) quote() (string, error) {
	if r.i >= r.n {
		return "", errCut
	}
	quote := r.text[r.i]
	r.i++
	var b strings.Builder
	for r.i < r.n {
		char := r.text[r.i]
		if char == quote {
			r.i++
			return b.String(), nil
		}
		if char == '\\' {
			esc, err := r.escape()
			if err != nil {
				return "", err
			}
			b.WriteString(esc)
			continue
		}
		if char == '\n' {
			return "", errRead
		}
		b.WriteByte(char)
		r.i++
	}
	return "", errCut
}

func (r *reader) escape() (string, error) {
	r.i++
	if r.i >= r.n {
		return "", errCut
	}
	char := r.text[r.i]
	r.i++
	switch char {
	case 'a':
		return "\a", nil
	case 'b':
		return "\b", nil
	case 'f':
		return "\f", nil
	case 'n':
		return "\n", nil
	case 'r':
		return "\r", nil
	case 't':
		return "\t", nil
	case 'v':
		return "\v", nil
	case '\\', '"', '\'':
		return string(char), nil
	case '\n':
		return "\n", nil
	}
	if char >= '0' && char <= '9' {
		digits := string(char)
		for n := 0; n < 2 && r.i < r.n && r.text[r.i] >= '0' && r.text[r.i] <= '9'; n++ {
			digits += string(r.text[r.i])
			r.i++
		}
		code, err := strconv.Atoi(digits)
		if err != nil || code > 255 {
			return "", errRead
		}
		return string(rune(code)), nil
	}
	return "", errRead
}

func (r *reader) longString() (string, error) {
	if err := r.expect("["); err != nil {
		return "", err
	}
	equals := 0
	for r.eat("=") {
		equals++
	}
	if err := r.expect("["); err != nil {
		return "", err
	}
	if r.peek() == '\n' {
		r.i++
	}
	close := "]" + strings.Repeat("=", equals) + "]"
	end := strings.Index(r.text[r.i:], close)
	if end < 0 {
		return "", errCut
	}
	text := r.text[r.i : r.i+end]
	r.i += end + len(close)
	return text, nil
}

func (r *reader) number() (any, error) {
	start := r.i
	if r.peek() == '-' {
		r.i++
	}
	saw := false
	for r.peek() >= '0' && r.peek() <= '9' {
		saw = true
		r.i++
	}
	float := false
	if r.peek() == '.' {
		float = true
		r.i++
		for r.peek() >= '0' && r.peek() <= '9' {
			saw = true
			r.i++
		}
	}
	if !saw {
		return nil, errRead
	}
	token := r.text[start:r.i]
	if float {
		value, err := strconv.ParseFloat(token, 64)
		if err != nil {
			return nil, errRead
		}
		return value, nil
	}
	value, err := strconv.ParseInt(token, 10, 64)
	if err != nil {
		return nil, errRead
	}
	return value, nil
}

func savedFiles(wowDir string) ([]string, error) {
	root := filepath.Join(wowDir, "WTF", "Account")
	info, err := os.Stat(root)
	if err != nil || !info.IsDir() {
		return nil, nil
	}
	matches, err := filepath.Glob(filepath.Join(root, "*", "SavedVariables", "Ironkeep.lua"))
	if err != nil {
		return nil, err
	}
	var files []string
	for _, match := range matches {
		info, err := os.Stat(match)
		if err == nil && !info.IsDir() {
			files = append(files, match)
		}
	}
	sort.Strings(files)
	return files, nil
}

func newest(files []string) (string, error) {
	if len(files) == 0 {
		return "", errNoDB
	}
	best := files[0]
	bestInfo, err := os.Stat(best)
	if err != nil {
		return "", err
	}
	for _, file := range files[1:] {
		info, err := os.Stat(file)
		if err != nil {
			return "", err
		}
		if info.ModTime().After(bestInfo.ModTime()) {
			best = file
			bestInfo = info
		}
	}
	return best, nil
}

func asMap(value any) map[any]any {
	table, _ := value.(map[any]any)
	return table
}

func asString(value any) string {
	text, _ := value.(string)
	return text
}

func asNumber(value any) (float64, bool) {
	switch n := value.(type) {
	case int64:
		return float64(n), true
	case float64:
		return n, true
	default:
		return 0, false
	}
}

var roleOrder = map[string]int{"TANK": 1, "HEALER": 2, "DAMAGER": 3}
var roleLabel = map[string]string{"TANK": "Tank", "HEALER": "Healer", "DAMAGER": "Damage"}

func rows(session map[any]any) []map[any]any {
	people := asMap(session["people"])
	list := make([]map[any]any, 0, len(people))
	for _, value := range people {
		if person, ok := value.(map[any]any); ok {
			list = append(list, person)
		}
	}
	sort.SliceStable(list, func(i, j int) bool {
		return personLess(list[i], list[j])
	})
	return list
}

func personLess(a, b map[any]any) bool {
	aPresent, bPresent := 1, 1
	if a["present"] == true {
		aPresent = 0
	}
	if b["present"] == true {
		bPresent = 0
	}
	if aPresent != bPresent {
		return aPresent < bPresent
	}
	aGroup, bGroup := 99.0, 99.0
	if n, ok := asNumber(a["subgroup"]); ok {
		aGroup = n
	}
	if n, ok := asNumber(b["subgroup"]); ok {
		bGroup = n
	}
	if aGroup != bGroup {
		return aGroup < bGroup
	}
	aRole := roleOrder[asString(a["role"])]
	bRole := roleOrder[asString(b["role"])]
	if aRole == 0 {
		aRole = 9
	}
	if bRole == 0 {
		bRole = 9
	}
	if aRole != bRole {
		return aRole < bRole
	}
	return asString(a["name"]) < asString(b["name"])
}

func seen(person map[any]any) string {
	first, okFirst := asNumber(person["first"])
	last, okLast := asNumber(person["last"])
	if !okFirst || !okLast {
		return ""
	}
	minutes := int(math.Floor((last - first) / 60))
	if minutes < 1 {
		return "<1m"
	}
	if minutes < 60 {
		return fmt.Sprintf("%dm", minutes)
	}
	return fmt.Sprintf("%dh %dm", minutes/60, minutes%60)
}

func report(session map[any]any, startedAt string) string {
	if session == nil {
		return "Ironkeep group\n\nNobody recorded yet."
	}
	if startedAt == "" {
		if started, ok := asNumber(session["started"]); ok {
			startedAt = time.Unix(int64(started), 0).Local().Format("2006-01-02 15:04")
		}
	}
	place := asString(session["place"])
	if place == "" {
		place = "Unknown"
	}
	lines := []string{
		"Ironkeep group",
		"Place: " + place,
		"Started: " + startedAt,
		"",
		"Name | Class | Role | Time | Status",
	}
	people := rows(session)
	for _, person := range people {
		status := "left"
		if person["present"] == true {
			status = "here"
		}
		name := asString(person["name"])
		if name == "" {
			name = "Unknown"
		}
		className := asString(person["className"])
		if className == "" {
			className = asString(person["classFile"])
		}
		lines = append(lines, strings.Join([]string{
			name,
			className,
			roleLabel[asString(person["role"])],
			seen(person),
			status,
		}, " | "))
	}
	if len(people) == 0 {
		lines = append(lines, "Nobody recorded yet.")
	}
	lines = append(lines, "", "format: ironkeep-group 1")
	return strings.Join(lines, "\n")
}

func textFor(db map[any]any) string {
	if session := asMap(db["session"]); session != nil {
		return report(session, "")
	}
	if previous := asString(db["lastReport"]); strings.TrimSpace(previous) != "" {
		return previous
	}
	return "Ironkeep group\n\nNobody recorded yet."
}
