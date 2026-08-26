on run argv
    set notificationKind to item 1 of argv

    if notificationKind is "success" then
        set reportPath to item 2 of argv
        set response to display dialog "今日 GitHub Agent Trending 研究简报已生成。" ¬
            buttons {"稍后", "打开简报"} default button "打开简报" ¬
            with title "Agent Trending Daily" with icon note giving up after 3600
        if gave up of response then return "none"
        if button returned of response is "打开简报" then return reportPath
        return "none"
    end if

    set logPath to item 2 of argv
    set response to display dialog "今日研究简报生成失败，旧日报未被覆盖。" ¬
        buttons {"关闭", "查看日志"} default button "查看日志" ¬
        with title "Agent Trending Daily" with icon caution giving up after 3600
    if gave up of response then return "none"
    if button returned of response is "查看日志" then return logPath
    return "none"
end run
