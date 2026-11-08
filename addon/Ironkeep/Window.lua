-- The group as the site shows a raid: by role, not as a table.
-- Drag the title. Copy list opens the text. It stays on this computer.

Ironkeep = Ironkeep or {}
Ironkeep.Window = {}

local MEDIA = "Interface\\AddOns\\Ironkeep\\Media\\"
local FONT = MEDIA .. "Inter-Regular.ttf"
local FONT_SEMI = MEDIA .. "Inter-SemiBold.ttf"

local BG = { 0.047, 0.055, 0.071, 1 }
local PANEL = { 0.075, 0.086, 0.110, 1 }
local PANEL_3 = { 0.118, 0.137, 0.169, 1 }
local BORDER = { 0.141, 0.165, 0.200, 1 }
local BORDER_STRONG = { 0.192, 0.220, 0.263, 1 }
local TEXT = { 0.906, 0.914, 0.925, 1 }
local TEXT_2 = { 0.765, 0.784, 0.812, 1 }
local MUTED = { 0.553, 0.584, 0.631, 1 }
local ACCENT = { 0.176, 0.831, 0.749, 1 }
local ACCENT_STRONG = { 0.369, 0.918, 0.831, 1 }
local ACCENT_INK = { 0.024, 0.145, 0.129, 1 }
local GREEN = { 0.247, 0.824, 0.561, 1 }
local GREEN_BG = { 0.247, 0.824, 0.561, 0.10 }
local RED_BG = { 0.949, 0.427, 0.427, 0.10 }
local RED_BORDER = { 0.949, 0.427, 0.427, 0.40 }
local RED_TEXT = { 1, 0.612, 0.612, 1 }

local ROW_CAP = 200
local REPORT_HEIGHT = 140
local REPORT_BOTTOM = 48
local REPORT_LABEL_Y = REPORT_BOTTOM + REPORT_HEIGHT + 6
local LIST_BOTTOM_CLOSED = 52
-- The hint can wrap onto a second line. Keep the group list above it.
local LIST_BOTTOM_OPEN = REPORT_LABEL_Y + 44
local COPY_HINT = "The report is selected. Press Ctrl+C to copy. It stays on this computer."
local PREVIOUS_HINT = "Previous list. The report is selected. Press Ctrl+C to copy."

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
local reportFocusLock = false

local function reportFocused()
	return reportBox and reportBox.HasFocus and reportBox:HasFocus() and true or false
end

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
	elseif button.kind == "quiet" then
		bg = { 0, 0, 0, 0 }
		border = { 0, 0, 0, 0 }
		text = hover and TEXT or MUTED
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

local function pill(parent)
	local frame = CreateFrame("Frame", nil, parent)
	frame:SetHeight(20)
	frame.bg = solid(frame)
	frame.bg:SetAllPoints()
	frame.label = face(frame:CreateFontString(nil, "OVERLAY"), 11, true)
	frame.label:SetPoint("CENTER")
	frame:Hide()
	return frame
end

local function showPill(frame, text, fg, bg)
	frame.label:SetText(text)
	frame.label:SetTextColor(fg[1], fg[2], fg[3])
	local width = frame.label:GetStringWidth() or 0
	if width < 8 then width = #text * 7 end
	frame:SetWidth(width + 14)
	tint(frame.bg, bg)
	frame:Show()
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
	window.confirmText:SetShown(window.confirming)
	window.confirmYes:SetShown(window.confirming)
	window.confirmNo:SetShown(window.confirming)
end

local function kindLabel(instanceType)
	if instanceType == "raid" then return "Raid" end
	if instanceType == "party" then return "Dungeon" end
	return "Group"
end

local function applyRow(row, item, session)
	if not item then
		row:Hide()
		return
	end
	row:Show()
	if item.kind == "lane" then
		row.swatch:Hide()
		row.group:SetText("")
		row.name:SetText(item.label)
		row.name:ClearAllPoints()
		row.name:SetPoint("LEFT", 4, 0)
		if item.key == "LEFT" then
			row.name:SetTextColor(RED_TEXT[1], RED_TEXT[2], RED_TEXT[3])
		else
			row.name:SetTextColor(TEXT[1], TEXT[2], TEXT[3])
		end
		row.count:SetText(tostring(item.count))
		row.count:SetTextColor(MUTED[1], MUTED[2], MUTED[3])
		local width = row.name:GetStringWidth() or 0
		if width < 8 then width = #item.label * 8 end
		row.count:ClearAllPoints()
		row.count:SetPoint("LEFT", row.name, "LEFT", width + 8, 0)
		row.time:SetText("")
		return
	end

	local person = item.person
	row.swatch:Show()
	local color = CLASS_COLOR[person.classFile] or ACCENT
	local alpha = person.present and 1 or 0.45
	row.swatch:SetVertexColor(color[1], color[2], color[3], alpha)
	row.name:ClearAllPoints()
	row.name:SetPoint("RIGHT", row.time, "LEFT", -8, 0)
	row.name:SetText(person.name or "Unknown")
	row.name:SetTextColor(color[1], color[2], color[3], alpha)
	if session.instanceType == "raid" and person.subgroup then
		row.group:SetText(tostring(person.subgroup))
		row.name:SetPoint("LEFT", row.group, "RIGHT", 4, 0)
	else
		row.group:SetText("")
		row.name:SetPoint("LEFT", row.swatch, "RIGHT", 8, 0)
	end
	row.count:SetText("")
	local seen = Ironkeep.Group.Seen(person)
	if person.present then
		row.time:SetText(seen)
		row.time:SetTextColor(MUTED[1], MUTED[2], MUTED[3])
	else
		row.time:SetText(seen)
		row.time:SetTextColor(RED_TEXT[1], RED_TEXT[2], RED_TEXT[3])
	end
end

local function makeRow(parent, index)
	local row = CreateFrame("Frame", nil, parent)
	row:SetSize(396, 22)
	row.swatch = solid(row, "ARTWORK")
	row.swatch:SetSize(8, 8)
	row.swatch:SetPoint("LEFT", 2, 0)
	row.group = face(row:CreateFontString(nil, "OVERLAY"), 12, false)
	row.group:SetPoint("LEFT", 16, 0)
	row.group:SetWidth(14)
	row.group:SetJustifyH("LEFT")
	row.group:SetTextColor(MUTED[1], MUTED[2], MUTED[3])
	row.time = face(row:CreateFontString(nil, "OVERLAY"), 12, false)
	row.time:SetPoint("RIGHT", -2, 0)
	row.time:SetWidth(52)
	row.time:SetJustifyH("RIGHT")
	row.name = face(row:CreateFontString(nil, "OVERLAY"), 13, true)
	row.name:SetJustifyH("LEFT")
	row.name:SetWordWrap(false)
	if row.name.SetMaxLines then row.name:SetMaxLines(1) end
	row.count = face(row:CreateFontString(nil, "OVERLAY"), 12, false)
	row:Hide()
	rows[index] = row
	return row
end

local function placePills()
	local x = 16
	local function put(frame)
		if not frame:IsShown() then return end
		frame:ClearAllPoints()
		frame:SetPoint("TOPLEFT", window, "TOPLEFT", x, -50)
		x = x + frame:GetWidth() + 6
	end
	put(window.kindPill)
	put(window.herePill)
	put(window.leftPill)
	window.started:ClearAllPoints()
	if x > 16 then
		window.started:SetPoint("TOPLEFT", window, "TOPLEFT", x + 2, -52)
		window.started:Show()
	else
		window.started:Hide()
	end
end

local function layoutChrome()
	local open = window.reportOpen and true or false
	local confirm = window.confirming and true or false
	local hasPrevious = Ironkeep.db and Ironkeep.db.lastReport and true or false
	window.copy:SetShown(not confirm)
	window.clear:SetShown(not confirm)
	window.previous:SetShown(not confirm and hasPrevious)
	window.reportLabel:SetShown(open and not confirm)
	window.reportScroll:SetShown(open)
	window.reportBorder:SetShown(open)
	window.scroll:ClearAllPoints()
	window.scroll:SetPoint("TOPLEFT", 12, -80)
	window.scroll:SetPoint("BOTTOMRIGHT", -12, open and LIST_BOTTOM_OPEN or LIST_BOTTOM_CLOSED)
	window.copy:SetText(open and "Hide" or "Copy list")
	if Ironkeep.showingPrevious then
		window.previous:SetText("Current")
	else
		window.previous:SetText("Previous")
	end
end

function Ironkeep.Window.Build()
	if window then return end

	window = frameWithBackdrop("IronkeepFrame", UIParent)
	window:SetSize(420, 480)
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
	title:SetHeight(36)
	title:EnableMouse(true)
	title:RegisterForDrag("LeftButton")
	title:SetScript("OnDragStart", function() window:StartMoving() end)
	title:SetScript("OnDragStop", function()
		window:StopMovingOrSizing()
		savePoint()
	end)

	local logo = title:CreateTexture(nil, "ARTWORK")
	logo:SetSize(22, 22)
	logo:SetPoint("LEFT", 8, 0)
	logo:SetTexture(MEDIA .. "logo.tga")

	local close = button(title, "Close", 48, "quiet")
	close:SetPoint("RIGHT", -2, 0)
	close:SetScript("OnClick", function() Ironkeep.Window.Hide() end)

	window.place = face(title:CreateFontString(nil, "OVERLAY"), 16, true)
	window.place:SetPoint("LEFT", logo, "RIGHT", 8, 0)
	window.place:SetPoint("RIGHT", close, "LEFT", -8, 0)
	window.place:SetJustifyH("LEFT")
	window.place:SetWordWrap(false)
	window.place:SetTextColor(TEXT[1], TEXT[2], TEXT[3])

	window.kindPill = pill(window)
	window.herePill = pill(window)
	window.leftPill = pill(window)
	window.started = face(window:CreateFontString(nil, "OVERLAY"), 12, false)
	window.started:SetTextColor(MUTED[1], MUTED[2], MUTED[3])

	local scroll = CreateFrame("ScrollFrame", nil, window)
	scroll:SetPoint("TOPLEFT", 12, -80)
	scroll:SetPoint("BOTTOMRIGHT", -12, LIST_BOTTOM_CLOSED)
	scroll:EnableMouseWheel(true)
	scroll:SetScript("OnMouseWheel", function(self, delta)
		local nextScroll = self:GetVerticalScroll() - delta * 44
		local maxScroll = self:GetVerticalScrollRange()
		if nextScroll < 0 then nextScroll = 0 end
		if nextScroll > maxScroll then nextScroll = maxScroll end
		self:SetVerticalScroll(nextScroll)
	end)
	local child = CreateFrame("Frame", nil, scroll)
	child:SetSize(396, 22)
	scroll:SetScrollChild(child)
	window.scroll = scroll
	window.list = child

	window.empty = face(window:CreateFontString(nil, "OVERLAY"), 12, false)
	window.empty:SetPoint("TOPLEFT", 16, -88)
	window.empty:SetWidth(388)
	window.empty:SetJustifyH("LEFT")
	window.empty:SetTextColor(MUTED[1], MUTED[2], MUTED[3])

	local copy = button(window, "Copy list", 96, "accent")
	copy:SetPoint("BOTTOMLEFT", 16, 14)
	copy:SetScript("OnClick", function()
		setConfirm(false)
		window.reportOpen = not window.reportOpen
		if window.reportOpen then
			window.reportSelect = true
		else
			Ironkeep.showingPrevious = false
		end
		Ironkeep.Window.Update()
	end)

	local previous = button(window, "Previous", 84, "ghost")
	previous:SetPoint("LEFT", copy, "RIGHT", 8, 0)
	previous:SetScript("OnClick", function()
		setConfirm(false)
		Ironkeep.showingPrevious = not Ironkeep.showingPrevious
		window.reportOpen = true
		window.reportSelect = true
		Ironkeep.Window.Update()
	end)

	local clear = button(window, "Clear", 64, "danger")
	clear:SetPoint("BOTTOMRIGHT", -16, 14)
	clear:SetScript("OnClick", function()
		if not Ironkeep.db or not Ironkeep.db.session then return end
		setConfirm(true)
		Ironkeep.Window.Update()
	end)

	local confirmText = face(window:CreateFontString(nil, "OVERLAY"), 12, true)
	confirmText:SetPoint("BOTTOMLEFT", 16, 20)
	confirmText:SetText("Clear this list?")
	confirmText:SetTextColor(TEXT[1], TEXT[2], TEXT[3])
	confirmText:Hide()

	local confirmNo = button(window, "Cancel", 72, "ghost")
	confirmNo:SetPoint("BOTTOMRIGHT", -16, 14)
	confirmNo:SetScript("OnClick", function()
		setConfirm(false)
		Ironkeep.Window.Update()
	end)
	confirmNo:Hide()

	local confirmYes = button(window, "Clear", 64, "danger")
	confirmYes:SetPoint("RIGHT", confirmNo, "LEFT", -8, 0)
	confirmYes:SetScript("OnClick", function()
		setConfirm(false)
		window.reportOpen = false
		Ironkeep.ClearSession()
	end)
	confirmYes:Hide()

	local reportLabel = face(window:CreateFontString(nil, "OVERLAY"), 11, false)
	reportLabel:SetPoint("BOTTOMLEFT", 16, REPORT_LABEL_Y)
	reportLabel:SetWidth(388)
	reportLabel:SetJustifyH("LEFT")
	reportLabel:SetWordWrap(true)
	reportLabel:SetTextColor(MUTED[1], MUTED[2], MUTED[3])
	reportLabel:SetText(COPY_HINT)
	reportLabel:Hide()

	local reportScroll = CreateFrame("ScrollFrame", nil, window)
	reportScroll:SetPoint("BOTTOMLEFT", 16, REPORT_BOTTOM)
	reportScroll:SetSize(388, REPORT_HEIGHT)
	reportScroll:Hide()
	local reportBorder = frameWithBackdrop(nil, window)
	reportBorder:SetPoint("TOPLEFT", reportScroll, "TOPLEFT", -4, 4)
	reportBorder:SetPoint("BOTTOMRIGHT", reportScroll, "BOTTOMRIGHT", 4, -4)
	reportBorder:SetFrameLevel(window:GetFrameLevel())
	reportBorder:Hide()
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
	reportBox:SetTextColor(TEXT_2[1], TEXT_2[2], TEXT_2[3])
	reportBox:SetWidth(372)
	-- Forever treats 0 as no letter cap. A positive value truncates SetText.
	reportBox:SetMaxLetters(0)
	if reportBox.SetTextInsets then reportBox:SetTextInsets(8, 8, 4, 4) end
	local function scrollReport(_, delta)
		local nextScroll = reportScroll:GetVerticalScroll() - delta * 28
		local maxScroll = reportScroll:GetVerticalScrollRange()
		if nextScroll < 0 then nextScroll = 0 end
		if nextScroll > maxScroll then nextScroll = maxScroll end
		reportScroll:SetVerticalScroll(nextScroll)
	end
	reportScroll:EnableMouseWheel(true)
	reportScroll:SetScript("OnMouseWheel", scrollReport)
	reportBox:EnableMouseWheel(true)
	reportBox:SetScript("OnMouseWheel", scrollReport)
	reportBox:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
	reportBox:SetScript("OnEditFocusGained", function(self) self:HighlightText() end)
	reportBox:SetScript("OnEditFocusLost", function()
		if reportFocusLock then return end
		Ironkeep.Window.Update()
	end)
	reportScroll:SetScrollChild(reportBox)

	window.reportLabel = reportLabel
	window.reportScroll = reportScroll
	window.reportBorder = reportBorder
	window.copy = copy
	window.previous = previous
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
	if not window or reportFocusLock then return end
	local db = Ironkeep.db
	local session = db and db.session
	if not session then setConfirm(false) end

	window.kindPill:Hide()
	window.herePill:Hide()
	window.leftPill:Hide()
	if not session then
		window.place:SetText("No group yet")
		window.empty:SetText("Join a party or a raid. The list fills itself, also while this window is closed.")
		window.empty:Show()
	else
		local here, gone = 0, 0
		for _, person in pairs(session.people) do
			if person.present then here = here + 1 else gone = gone + 1 end
		end
		window.place:SetText(session.place or "Unknown")
		showPill(window.kindPill, kindLabel(session.instanceType), TEXT_2, PANEL_3)
		showPill(window.herePill, here .. " here", GREEN, GREEN_BG)
		if gone > 0 then showPill(window.leftPill, gone .. " left", RED_TEXT, RED_BG) end
		window.empty:Hide()
	end
	if session and session.started and date then
		window.started:SetText(date("%H:%M", session.started))
	else
		window.started:SetText("")
	end
	placePills()

	local items = Ironkeep.Group.Lanes(session)
	if #items > ROW_CAP then
		local trimmed = {}
		for i = 1, ROW_CAP do trimmed[i] = items[i] end
		items = trimmed
	end
	local y = 0
	for i = 1, #items do
		local item = items[i]
		local row = rows[i] or makeRow(window.list, i)
		local height = 22
		local gap = 0
		if item.kind == "lane" then
			height = 24
			if i > 1 then gap = 10 end
		end
		row:ClearAllPoints()
		row:SetPoint("TOPLEFT", 0, -(y + gap))
		row:SetHeight(height)
		applyRow(row, item, session or {})
		y = y + gap + height
	end
	for i = #items + 1, #rows do rows[i]:Hide() end
	window.list:SetHeight(math.max(y, 1))

	layoutChrome()
	if not window.reportOpen then
		window.reportSelect = false
		if reportFocused() and reportBox.ClearFocus then
			reportFocusLock = true
			reportBox:ClearFocus()
			reportFocusLock = false
		end
		return
	end
	local text
	if Ironkeep.showingPrevious then
		text = (db and db.lastReport) or "Ironkeep group\n\nNo previous list."
		window.reportLabel:SetText(PREVIOUS_HINT)
	else
		text = Ironkeep.Group.Report(session, time and time() or 0)
		window.reportLabel:SetText(COPY_HINT)
	end
	local _, breaks = text:gsub("\n", "\n")
	reportBox:SetHeight(math.max(REPORT_HEIGHT, (breaks + 1) * 14))
	if window.reportSelect then
		window.reportSelect = false
		reportFocusLock = true
		reportBox:SetText(text)
		reportBox._last = text
		if reportBox.SetFocus then reportBox:SetFocus() end
		if reportBox.HighlightText then reportBox:HighlightText() end
		if window.reportScroll.SetVerticalScroll then window.reportScroll:SetVerticalScroll(0) end
		reportFocusLock = false
		return
	end
	if not reportFocused() and reportBox._last ~= text then
		reportBox:SetText(text)
		reportBox._last = text
	end
end
