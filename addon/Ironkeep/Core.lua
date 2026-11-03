-- Group list for one officer inside a WoW: Forever party or raid.
-- The list stays on this computer. The window can copy it out as text.

Ironkeep = Ironkeep or {}

BINDING_HEADER_IRONKEEP = "Ironkeep"
BINDING_NAME_IRONKEEP_TOGGLE = "Open the group list"

local IDLE_SECONDS = 20 * 60

local frame = CreateFrame("Frame")
local ticker = CreateFrame("Frame", nil, UIParent)
local elapsed = 0
ticker:SetSize(1, 1)
ticker:SetPoint("TOPLEFT", UIParent, "TOPLEFT", 0, 0)
ticker:EnableMouse(false)

function Ironkeep.Print(message)
	print("|cffc6a15aIronkeep|r " .. tostring(message))
end

function Ironkeep.Init()
	if Ironkeep.db then return end
	IronkeepDB = IronkeepDB or {}
	Ironkeep.db = IronkeepDB
	Ironkeep.Window.Build()
	Ironkeep.Refresh()
	if Ironkeep.db.open then
		Ironkeep.Window.Show()
	end
end

function Ironkeep.Refresh()
	if not Ironkeep.db then return end
	local ok, snapshot = pcall(Ironkeep.Group.Read)
	if not ok then
		if not Ironkeep.readFailed then
			Ironkeep.readFailed = true
			Ironkeep.Print("Could not read the group: " .. tostring(snapshot))
		end
		return
	end

	local now = time()
	local db = Ironkeep.db
	if Ironkeep.Group.ShouldRestart(db.session, snapshot, now, IDLE_SECONDS) then
		if db.session then
			db.lastReport = Ironkeep.Group.Report(db.session, now)
		end
		db.session = Ironkeep.Group.NewSession(snapshot, now)
	end
	if db.session then
		Ironkeep.Group.Merge(db.session, snapshot, now)
	end

	if snapshot.count > 0 and not Ironkeep.announced and not Ironkeep.db.open and not Ironkeep.Window.IsShown() then
		Ironkeep.announced = true
		Ironkeep.Print("You are in a group. /ironkeep opens the list.")
	end

	Ironkeep.Window.Update()
end

function Ironkeep.ClearSession()
	local db = Ironkeep.db
	if not db then return end
	if db.session then
		db.lastReport = Ironkeep.Group.Report(db.session, time())
		db.session = nil
	end
	Ironkeep.showingPrevious = false
	Ironkeep.Refresh()
end

function Ironkeep.Toggle()
	if not Ironkeep.db then
		Ironkeep.Print("Still loading.")
		return
	end
	if Ironkeep.Window.IsShown() then
		Ironkeep.Window.Hide()
	else
		Ironkeep.Window.Show()
	end
end

frame:SetScript("OnEvent", function(_, event, name)
	if event == "ADDON_LOADED" then
		if name == "Ironkeep" then Ironkeep.Init() end
		return
	end
	Ironkeep.Refresh()
end)

local function listen(event)
	pcall(frame.RegisterEvent, frame, event)
end

listen("ADDON_LOADED")
listen("GROUP_ROSTER_UPDATE")
listen("PARTY_MEMBERS_CHANGED")
listen("RAID_ROSTER_UPDATE")
listen("PLAYER_ENTERING_WORLD")

ticker:SetScript("OnUpdate", function(_, delta)
	if not Ironkeep.db then return end
	elapsed = elapsed + delta
	if elapsed < 30 then return end
	elapsed = 0
	Ironkeep.Refresh()
end)

SLASH_IRONKEEP1 = "/ironkeep"
SLASH_IRONKEEP2 = "/ik"
SlashCmdList.IRONKEEP = function()
	Ironkeep.Toggle()
end
