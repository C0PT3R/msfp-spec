package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"sort"
	"strconv"
	"strings"
)

// The parts of version 1 (spec/v1/core.md section 10.1).
var knownParts = map[string]bool{"catalog": true, "playback": true, "media": true, "video": true, "music": true}

var partName = regexp.MustCompile(`^[a-z-]{1,32}$`)

// versionList reads a version list of a hello (spec/v1/core.md section
// 10.2): an array, of which the first 8 entries count; entries that
// aren't non-negative integers (section 2.3) are ignored, and duplicates
// count once.
func versionList(raw json.RawMessage) ([]int64, error) {
	var entries []json.RawMessage
	if err := json.Unmarshal(raw, &entries); err != nil || entries == nil {
		return nil, errors.New("a version list that isn't an array")
	}
	if len(entries) > 8 {
		entries = entries[:8]
	}
	seen := map[int64]bool{}
	out := []int64{}
	for _, e := range entries {
		t := strings.TrimSpace(string(e))
		if t == "" || !(t[0] == '-' || (t[0] >= '0' && t[0] <= '9')) {
			continue // not a number
		}
		if checkInteger(t) != nil || strings.HasPrefix(t, "-") {
			continue // a number, but not a non-negative integer
		}
		n, _ := strconv.ParseInt(t, 10, 64)
		if !seen[n] {
			seen[n] = true
			out = append(out, n)
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i] < out[j] })
	return out, nil
}

// keptVersions is what a receiver keeps of a hello's core and parts
// (spec/v1/core.md section 10.2), written as JSON: the core versions,
// and each known part's versions, by name. A bad body is an error.
func keptVersions(body []byte) (string, error) {
	if err := checkIJSON(body); err != nil {
		return "", err
	}
	var top map[string]json.RawMessage
	if err := json.Unmarshal(body, &top); err != nil || top == nil {
		return "", errors.New("not a JSON object")
	}
	var state string
	if err := json.Unmarshal(top["state"], &state); err != nil || bytes.Equal(top["state"], []byte("null")) {
		return "", errors.New("no state, or one that isn't a string")
	}
	core := []int64{}
	if raw, ok := top["core"]; ok {
		var err error
		if core, err = versionList(raw); err != nil {
			return "", fmt.Errorf("core: %v", err)
		}
	}
	parts := map[string][]int64{}
	if raw, ok := top["parts"]; ok {
		var m map[string]json.RawMessage
		if err := json.Unmarshal(raw, &m); err != nil || m == nil {
			return "", errors.New("parts isn't an object")
		}
		for name, v := range m {
			if !partName.MatchString(name) || !knownParts[name] {
				continue // unknown: ignored, whatever its value
			}
			l, err := versionList(v)
			if err != nil {
				return "", fmt.Errorf("parts.%s: %v", name, err)
			}
			parts[name] = l
		}
	}
	out, _ := json.Marshal(struct {
		Core  []int64            `json:"core"`
		Parts map[string][]int64 `json:"parts"`
	}{core, parts})
	return string(out), nil
}

type helloVersionCase struct {
	Name   string `json:"name"`
	Text   string `json:"text"`
	Valid  bool   `json:"valid"`
	Reason string `json:"reason,omitempty"`
	Output string `json:"output,omitempty"`
}

// helloVersionCases are hello bodies with what a receiver keeps of their
// versions (spec/v1/core.md sections 2.3 and 10.2).
func helloVersionCases() []helloVersionCase {
	cases := []struct{ name, body string }{
		{"a number that isn't an integer is ignored", `{"state":"paired","core":[1,2.5]}`},
		{"in a part's list too", `{"state":"paired","core":[1],"parts":{"catalog":[1],"video":[1,2.5]}}`},
		{"entries that aren't non-negative integers are ignored", `{"state":"paired","core":[1,1.0,1e0,-1,-0,"2",null,true,[3]]}`},
		{"only the first 8 entries count", `{"state":"paired","core":[0,1,2,3,4,5,6,7,8]}`},
		{"duplicates count once", `{"state":"paired","core":[1,1],"parts":{"media":[2,1,2]}}`},
		{"no core: none", `{"state":"paired"}`},
		{"an empty core: none", `{"state":"paired","core":[]}`},
		{"unknown parts are ignored, whatever their value, null included", `{"state":"paired","core":[1],"parts":{"catalog":[1],"later":null,"x-y":{"v":1},"Catalog":"1"}}`},
		{"an unknown member is ignored, null included", `{"state":"paired","core":[1],"later":null}`},
		{"a core that isn't an array: a bad body", `{"state":"paired","core":"1"}`},
		{"a core of null: a bad body", `{"state":"paired","core":null}`},
		{"a known part that isn't an array: a bad body", `{"state":"paired","core":[1],"parts":{"catalog":1}}`},
		{"a known part of null: a bad body", `{"state":"paired","core":[1],"parts":{"catalog":null}}`},
		{"parts that isn't an object: a bad body", `{"state":"paired","core":[1],"parts":[]}`},
	}
	var out []helloVersionCase
	for _, c := range cases {
		got, err := keptVersions([]byte(c.body))
		ok, r := reason(err)
		out = append(out, helloVersionCase{c.name, c.body, ok, r, got})
	}
	return out
}
