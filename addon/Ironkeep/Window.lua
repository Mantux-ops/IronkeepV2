-- The in-game list, drawn with the same colors, type, and mark as ironkeep.gg.
-- Drag the title. The report box is there to copy.

Ironkeep = Ironkeep or {}
Ironkeep.Window = {}

local MEDIA = "Interface\\AddOns\\Ironkeep\\Media\\"
local FONT = MEDIA .. "Inter-Regular.ttf"
local FONT_SEMI = MEDIA .. "Inter-SemiBold.ttf"

local BG = { 0.047, 0.055, 0.071, 1 }
local PANEL = { 0.075, 0.086, 0.110, 1 }
local PANEL_2 = { 0.094, 0.110, 0.137, 1 }
local PANEL_3 = { 0.118, 0.137, 0.169, 1 }
local BORDER = { 0.141, 0.165, 0.200, 1 }
local BORDER_STRONG = { 0.192, 0.220, 0.263, 1 }
local TEXT = { 0.906, 0.914, 0.925, 1 }
local TEXT_2 = { 0.765, 0.784, 0.812, 1 }
local MUTED = { 0.553, 0.584, 0.631, 1 }
local ACCENT = { 0.176, 0.831, 0.749, 1 }
local ACCENT_STRONG = { 0.369, 0.918, 0.831, 1 }
local ACCENT_INK = { 0.024, 0.145, 0.129, 1 }
local RED_BG = { 0.949, 0.427, 0.427, 0.10 }
local RED_BORDER = { 0.949, 0.427, 0.427, 0.40 }
local RED_TEXT = { 1, 0.612, 0.612, 1 }

local ROW_H = 24
local ROW_CAP = 200

local CLASS_COLOR = {
	WARRIOR = { 0.78, 0.61, 0.43 },
	PALADIN = { 0.96, 0.55, 0.73 },
	HUNTER = { 0.67, 0.83, 0.45 },
	ROGUE = { 1.00, 0.96, 0.41 },
	PRIEST = { 1.00, 1.00, 1.00 },
	SHAMAN = { 0.00, 0.44, 0.87 },
	MAGE = { 0.41, 0.80, 0.94 },
	WARLOCK = { 0.58, 0.51, 0.79 },
	DRUID = { 1.00, 0.49, 0.04 },
}

local window
local rows = {}
local reportBox

local function face(widget, size, semi)
	local ok = widget.SetFont and widget:SetFont(semi and FONT_SEMI or FONT, size, "")
	if not ok and widget.SetFontObject then
		widget:SetFontObject(GameFontHighlightSmall)
	end
	return widget
end

local function solid(parent, layer)
	local texture = parent:CreateTexture(nil, layer or "BACKGROUND")
	texture:SetTexture("Interface\\Buttons\\WHITE8X8")
	return texture
end

local function tint(texture, color, alpha)
	texture:SetVertexColor(color[1], color[2], color[3], alpha or color[4] or 1)
end

local function frameWithBackdrop(name, parent)
	local ok, created = pcall(CreateFrame, "Frame", name, parent, "BackdropTemplate")
	if ok and created then return created end
	return CreateFrame("Frame", name, parent)
end

local function card(frame, edge, bg)
	if not frame.SetBackdrop then return false end
	local ok = pcall(frame.SetBackdrop, frame, {
		bgFile = MEDIA .. bg,
		edgeFile = MEDIA .. edge,
		edgeSize = 8,
		insets = { left = 8, right = 8, top = 8, bottom = 8 },
	})
	if not ok then return false end
	frame:SetBackdropColor(1, 1, 1, 1)
	frame:SetBackdropBorderColor(1, 1, 1, 1)
	return true
end

local function paintButton(button, hover)
	local bg, border, text = PANEL_3, BORDER, TEXT
	if button.kind == "accent" then
		bg = hover and ACCENT_STRONG or ACCENT
		border = bg
		text = ACCENT_INK
	elseif button.kind == "danger" then
		bg = hover and RED_BG or { 0, 0, 0, 0 }
		border = RED_BORDER
		text = RED_TEXT
	elseif hover then
		border = BORDER_STRONG
	end
	if button.SetBackdropColor then
		button:SetBackdropColor(bg[1], bg[2], bg[3], bg[4] or 1)
		button:SetBackdropBorderColor(border[1], border[2], border[3], border[4] or 1)
	end
	button.label:SetTextColor(text[1], text[2], text[3], text[4] or 1)
end

local function button(parent, label, width, kind)
	local ok, created = pcall(CreateFrame, "Button", nil, parent, "BackdropTemplate")
	local widget = (ok and created) or CreateFrame("Button", nil, parent)
	widget:SetSize(width, 26)
	widget.kind = kind
	if widget.SetBackdrop then
		pcall(widget.SetBackdrop, widget, {
			bgFile = "Interface\\Buttons\\WHITE8X8",
			edgeFile = "Interface\\Buttons\\WHITE8X8",
			edgeSize = 1,
			insets = { left = 1, right = 1, top = 1, bottom = 1 },
		})
	end
	widget.label = face(widget:CreateFontString(nil, "OVERLAY"), 12, true)
	widget.label:SetPoint("CENTER")
	widget.label:SetText(label)
	widget.SetText = function(self, value) self.label:SetText(value) end
	widget:SetScript("OnEnter", function(self) paintButton(self, true) end)
	widget:SetScript("OnLeave", function(self) paintButton(self, false) end)
	paintButton(widget, false)
	return widget
end

local function savePoint()
	if not window or not Ironkeep.db then return end
	local point, _, _, x, y = window:GetPoint(1)
	Ironkeep.db.point = point
	Ironkeep.db.x = x
	Ironkeep.db.y = y
end

local function setConfirm(on)
	if not window or not window.clear then return end
	window.confirming = on and true or false
	window.refresh:SetShown(not on)
	window.previous:SetShown(not on)
	window.clear:SetShown(not on)
	window.confirmText:SetShown(on)
	window.confirmYes:SetShown(on)
	window.confirmNo:SetShown(on)
end

local function kindLabel(instanceType)
	if instanceType == "raid" then return "Raid" end
	if instanceType == "party" then return "Dungeon" end
	return "Group"
end

local function counts(session)
	local here, gone = 0, 0
	if not session then return here, gone end
	for _, person in pairs(session.people) do
		if person.present then here = here + 1 else gone = gone + 1 end
	end
	return here, gone
end

local function applyRow(row, person, session)
	if not person then
		row:Hide()
		return
	end
	row:Show()
	local name = person.name or "Unknown"
	if session.instanceType == "raid" and person.subgroup then
		name = person.subgroup .. "  " .. name
	end
	row.name:SetText(name)
	local color = CLASS_COLOR[person.classFile]
	local alpha = person.present and 1 or 0.45
	if color then
		row.name:SetTextColor(color[1], color[2], color[3], alpha)
		row.swatch:SetVertexColor(color[1], color[2], color[3], alpha)
	else
		row.name:SetTextColor(TEXT[1], TEXT[2], TEXT[3], alpha)
		row.swatch:SetVertexColor(ACCENT[1], ACCENT[2], ACCENT[3], alpha)
	end
	row.className:SetText(person.className or "")
	row.role:SetText(Ironkeep.Group.RoleLabel(person.role))
	local seen = Ironkeep.Group.Seen(person)
	if person.present then
		row.seen:SetText(seen)
		row.seen:SetTextColor(TEXT_2[1], TEXT_2[2], TEXT_2[3])
		row.className:SetTextColor(TEXT_2[1], TEXT_2[2], TEXT_2[3])
		row.role:SetTextColor(TEXT_2[1], TEXT_2[2], TEXT_2[3])
	else
		row.seen:SetText(seen .. " left")
		row.seen:SetTextColor(RED_TEXT[1], RED_TEXT[2], RED_TEXT[3])
		row.className:SetTextColor(MUTED[1], MUTED[2], MUTED[3])
		row.role:SetTextColor(MUTED[1], MUTED[2], MUTED[3])
	end
end

local function makeRow(parent, index)
	local row = CreateFrame("Frame", nil, parent)
	row:SetSize(484, ROW_H)
	row:SetPoint("TOPLEFT", 0, -((index - 1) * ROW_H))
	local line = solid(row, "BORDER")
	line:SetPoint("BOTTOMLEFT", 8, 0)
	line:SetPoint("BOTTOMRIGHT", -8, 0)
	line:SetHeight(1)
	tint(line, BORDER)
	row.swatch = solid(row, "ARTWORK")
	row.swatch:SetPoint("LEFT", 10, 0)
	row.swatch:SetSize(8, 8)
	row.name = face(row:CreateFontString(nil, "OVERLAY"), 12, true)
	row.name:SetPoint("LEFT", 24, 0)
	row.name:SetWidth(166)
	row.name:SetJustifyH("LEFT")
	row.name:SetWordWrap(false)
	if row.name.SetMaxLines then row.name:SetMaxLines(1) end
	row.className = face(row:CreateFontString(nil, "OVERLAY"), 12, false)
	row.className:SetPoint("LEFT", 196, 0)
	row.className:SetWidth(84)
	row.className:SetJustifyH("LEFT")
	row.role = face(row:CreateFontString(nil, "OVERLAY"), 12, false)
	row.role:SetPoint("LEFT", 286, 0)
	row.role:SetWidth(74)
	row.role:SetJustifyH("LEFT")
	row.seen = face(row:CreateFontString(nil, "OVERLAY"), 12, false)
	row.seen:SetPoint("LEFT", 366, 0)
	row.seen:SetWidth(100)
	row.seen:SetJustifyH("LEFT")
	row:Hide()
	rows[index] = row
	return row
end

function Ironkeep.Window.Build()
	if window then return end

	window = frameWithBackdrop("IronkeepFrame", UIParent)
	window:SetSize(500, 560)
	window:SetFrameStrata("MEDIUM")
	window:SetClampedToScreen(true)
	window:SetMovable(true)
	window:EnableMouse(true)
	window:Hide()
	if not card(window, "panel-edge.tga", "panel-bg.tga") then
		local fill = solid(window)
		fill:SetAllPoints()
		tint(fill, PANEL)
	end

	local db = Ironkeep.db or {}
	window:ClearAllPoints()
	window:SetPoint(db.point or "CENTER", UIParent, db.point or "CENTER", db.x or 0, db.y or 40)

	local title = CreateFrame("Frame", nil, window)
	title:SetPoint("TOPLEFT", 8, -8)
	title:SetPoint("TOPRIGHT", -8, -8)
	title:SetHeight(44)
	title:EnableMouse(true)
	title:RegisterForDrag("LeftButton")
	title:SetScript("OnDragStart", function() window:StartMoving() end)
	title:SetScript("OnDragStop", function()
		window:StopMovingOrSizing()
		savePoint()
	end)

	local logo = title:CreateTexture(nil, "ARTWORK")
	logo:SetSize(28, 28)
	logo:SetPoint("LEFT", 8, 0)
	logo:SetTexture(MEDIA .. "logo.tga")

	local titleText = face(title:CreateFontString(nil, "OVERLAY"), 16, true)
	titleText:SetPoint("LEFT", logo, "RIGHT", 8, 0)
	titleText:SetText("Ironkeep")
	titleText:SetTextColor(TEXT[1], TEXT[2], TEXT[3])

	local close = button(title, "Close", 58, "ghost")
	close:SetPoint("RIGHT", -4, 0)
	close:SetScript("OnClick", function() Ironkeep.Window.Hide() end)

	local rule = solid(window, "BORDER")
	rule:SetPoint("TOPLEFT", 8, -52)
	rule:SetPoint("TOPRIGHT", -8, -52)
	rule:SetHeight(1)
	tint(rule, BORDER)

	window.place = face(window:CreateFontString(nil, "OVERLAY"), 14, true)
	window.place:SetPoint("TOPLEFT", 16, -60)
	window.place:SetWidth(468)
	window.place:SetJustifyH("LEFT")
	window.place:SetTextColor(TEXT[1], TEXT[2], TEXT[3])

	window.summary = face(window:CreateFontString(nil, "OVERLAY"), 12, false)
	window.summary:SetPoint("TOPLEFT", 16, -80)
	window.summary:SetWidth(468)
	window.summary:SetJustifyH("LEFT")
	window.summary:SetTextColor(MUTED[1], MUTED[2], MUTED[3])

	local columns = CreateFrame("Frame", nil, window)
	columns:SetPoint("TOPLEFT", 8, -112)
	columns:SetSize(484, 28)
	local columnFill = solid(columns)
	columnFill:SetAllPoints()
	tint(columnFill, PANEL_2)
	local columnLine = solid(columns, "BORDER")
	columnLine:SetPoint("BOTTOMLEFT")
	columnLine:SetPoint("BOTTOMRIGHT")
	columnLine:SetHeight(1)
	tint(columnLine, BORDER)

	local function column(text, x)
		local label = face(columns:CreateFontString(nil, "OVERLAY"), 11, true)
		label:SetPoint("LEFT", columns, "LEFT", x, 0)
		label:SetText(text)
		label:SetTextColor(MUTED[1], MUTED[2], MUTED[3])
	end
	column("NAME", 24)
	column("CLASS", 196)
	column("ROLE", 286)
	column("SEEN", 366)

	local scroll = CreateFrame("ScrollFrame", nil, window)
	scroll:SetPoint("TOPLEFT", 8, -140)
	scroll:SetPoint("BOTTOMRIGHT", -8, 168)
	scroll:EnableMouseWheel(true)
	scroll:SetScript("OnMouseWheel", function(self, delta)
		local nextScroll = self:GetVerticalScroll() - delta * ROW_H * 2
		local maxScroll = self:GetVerticalScrollRange()
		if nextScroll < 0 then nextScroll = 0 end
		if nextScroll > maxScroll then nextScroll = maxScroll end
		self:SetVerticalScroll(nextScroll)
	end)

	local child = CreateFrame("Frame", nil, scroll)
	child:SetSize(484, ROW_H)
	scroll:SetScrollChild(child)
	window.list = child

	local refresh = button(window, "Refresh", 84, "accent")
	refresh:SetPoint("BOTTOMLEFT", 16, 124)
	refresh:SetScript("OnClick", function()
		setConfirm(false)
		Ironkeep.Refresh()
	end)

	local previous = button(window, "Previous", 84, "ghost")
	previous:SetPoint("LEFT", refresh, "RIGHT", 8, 0)
	previous:SetScript("OnClick", function()
		setConfirm(false)
		Ironkeep.showingPrevious = not Ironkeep.showingPrevious
		Ironkeep.Window.Update()
	end)

	local clear = button(window, "Clear", 84, "danger")
	clear:SetPoint("LEFT", previous, "RIGHT", 8, 0)
	clear:SetScript("OnClick", function()
		if not Ironkeep.db or not Ironkeep.db.session then return end
		setConfirm(true)
		Ironkeep.Window.Update()
	end)

	local confirmText = face(window:CreateFontString(nil, "OVERLAY"), 12, true)
	confirmText:SetPoint("BOTTOMLEFT", 16, 130)
	confirmText:SetText("Clear this list?")
	confirmText:SetTextColor(TEXT[1], TEXT[2], TEXT[3])
	confirmText:Hide()

	local confirmNo = button(window, "Cancel", 84, "ghost")
	confirmNo:SetPoint("BOTTOMRIGHT", -16, 124)
	confirmNo:SetScript("OnClick", function()
		setConfirm(false)
		Ironkeep.Window.Update()
	end)
	confirmNo:Hide()

	local confirmYes = button(window, "Clear", 84, "danger")
	confirmYes:SetPoint("RIGHT", confirmNo, "LEFT", -8, 0)
	confirmYes:SetScript("OnClick", function()
		setConfirm(false)
		Ironkeep.ClearSession()
	end)
	confirmYes:Hide()

	local reportLabel = face(window:CreateFontString(nil, "OVERLAY"), 11, false)
	reportLabel:SetPoint("BOTTOMLEFT", 16, 104)
	reportLabel:SetTextColor(MUTED[1], MUTED[2], MUTED[3])
	reportLabel:SetText("Report. Click it, then copy. It stays on this computer.")

	local reportScroll = CreateFrame("ScrollFrame", nil, window)
	reportScroll:SetPoint("BOTTOMLEFT", 16, 14)
	reportScroll:SetSize(468, 84)
	local reportBorder = frameWithBackdrop(nil, window)
	reportBorder:SetPoint("TOPLEFT", reportScroll, "TOPLEFT", -4, 4)
	reportBorder:SetPoint("BOTTOMRIGHT", reportScroll, "BOTTOMRIGHT", 4, -4)
	reportBorder:SetFrameLevel(window:GetFrameLevel())
	if not card(reportBorder, "input-edge.tga", "input-bg.tga") then
		local fill = solid(reportBorder)
		fill:SetAllPoints()
		tint(fill, BG)
	end
	reportScroll:SetFrameLevel(reportBorder:GetFrameLevel() + 2)

	reportBox = CreateFrame("EditBox", nil, reportScroll)
	reportBox:SetMultiLine(true)
	reportBox:SetAutoFocus(false)
	face(reportBox, 11, false)
	reportBox:SetTextColor(TEXT[1], TEXT[2], TEXT[3])
	reportBox:SetWidth(452)
	reportBox:SetMaxLetters(8000)
	if reportBox.SetTextInsets then reportBox:SetTextInsets(8, 8, 6, 6) end
	reportBox:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
	reportBox:SetScript("OnEditFocusGained", function(self) self:HighlightText() end)
	reportBox:SetScript("OnEditFocusLost", function() Ironkeep.Window.Update() end)
	reportScroll:SetScrollChild(reportBox)

	window.reportLabel = reportLabel
	window.previous = previous
	window.refresh = refresh
	window.clear = clear
	window.confirmText = confirmText
	window.confirmYes = confirmYes
	window.confirmNo = confirmNo
end

function Ironkeep.Window.IsShown()
	return window and window:IsShown()
end

function Ironkeep.Window.Show()
	Ironkeep.Window.Build()
	window:Show()
	if Ironkeep.db then Ironkeep.db.open = true end
	Ironkeep.Window.Update()
end

function Ironkeep.Window.Hide()
	if not window then return end
	window:Hide()
	if Ironkeep.db then Ironkeep.db.open = false end
end

function Ironkeep.Window.Update()
	if not window then return end
	local db = Ironkeep.db
	local session = db and db.session
	if not session then setConfirm(false) end
	if not session then
		window.place:SetText("No group yet")
		window.summary:SetText("Join a party or a raid. The list fills itself, also while this window is closed.")
	else
		local here, gone = counts(session)
		local place = session.place or "Unknown"
		window.place:SetText(place .. " - " .. kindLabel(session.instanceType))
		local summary = here .. " here"
		if gone > 0 then summary = summary .. " - " .. gone .. " left" end
		if session.started and date then
			summary = summary .. " - started " .. date("%H:%M", session.started)
		end
		if here == 0 then
			summary = summary .. " - kept until you clear it"
		end
		window.summary:SetText(summary)
	end

	local people = Ironkeep.Group.Rows(session)
	local shown = math.min(#people, ROW_CAP)
	local child = window.list
	child:SetHeight(math.max(shown, 1) * ROW_H)
	for i = 1, shown do
		applyRow(rows[i] or makeRow(child, i), people[i], session or {})
	end
	for i = shown + 1, #rows do
		rows[i]:Hide()
	end

	if reportBox.HasFocus and reportBox:HasFocus() then return end
	local text
	if window.confirming then
		window.reportLabel:SetText("People still in the group start a new list.")
	elseif Ironkeep.showingPrevious then
		text = (db and db.lastReport) or "Ironkeep group\n\nNo previous list."
		window.reportLabel:SetText("Previous list. Click it, then copy.")
		window.previous:SetText("Current")
	else
		text = Ironkeep.Group.Report(session, time and time() or 0)
		window.reportLabel:SetText("Report. Click it, then copy. It stays on this computer.")
		window.previous:SetText("Previous")
	end
	if window.confirming then
		text = text or ((db and db.session) and Ironkeep.Group.Report(db.session, time and time() or 0) or "")
	end
	if not text then return end
	local _, breaks = text:gsub("\n", "\n")
	reportBox:SetHeight(math.max(84, (breaks + 1) * 14))
	if reportBox._last ~= text then
		reportBox:SetText(text)
		reportBox._last = text
	end
end
