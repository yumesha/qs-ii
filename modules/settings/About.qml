import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Widgets
import qs
import qs.services
import qs.modules.common
import qs.modules.common.widgets

ContentPage {
    id: root
    forceWidth: true
    readonly property string repositoryUrl: "https://github.com/yumesha/qs-ii"

    ContentSection {
        icon: "box"
        title: Translation.tr("Distro")
        
        RowLayout {
            Layout.alignment: Qt.AlignHCenter
            spacing: 20
            Layout.topMargin: 10
            Layout.bottomMargin: 10
            IconImage {
                implicitSize: 80
                source: Quickshell.iconPath(SystemInfo.logo)
            }
            ColumnLayout {
                Layout.alignment: Qt.AlignVCenter
                // spacing: 10
                StyledText {
                    text: SystemInfo.distroName
                    font.pixelSize: Appearance.font.pixelSize.title
                }
                StyledText {
                    font.pixelSize: Appearance.font.pixelSize.normal
                    text: SystemInfo.homeUrl
                    textFormat: Text.MarkdownText
                    onLinkActivated: (link) => {
                        Qt.openUrlExternally(link)
                    }
                    PointingHandLinkHover {}
                }
            }
        }

        Flow {
            Layout.fillWidth: true
            spacing: 5

            RippleButtonWithIcon {
                materialIcon: "auto_stories"
                mainText: Translation.tr("Documentation")
                onClicked: {
                    Qt.openUrlExternally(SystemInfo.documentationUrl)
                }
            }
            RippleButtonWithIcon {
                materialIcon: "support"
                mainText: Translation.tr("Help & Support")
                onClicked: {
                    Qt.openUrlExternally(SystemInfo.supportUrl)
                }
            }
            RippleButtonWithIcon {
                materialIcon: "bug_report"
                mainText: Translation.tr("Report a Bug")
                onClicked: {
                    Qt.openUrlExternally(SystemInfo.bugReportUrl)
                }
            }
            RippleButtonWithIcon {
                materialIcon: "policy"
                materialIconFill: false
                mainText: Translation.tr("Privacy Policy")
                onClicked: {
                    Qt.openUrlExternally(SystemInfo.privacyPolicyUrl)
                }
            }
            
        }

    }
    ContentSection {
        icon: "folder_managed"
        title: Translation.tr("Dotfiles")

        RowLayout {
            Layout.alignment: Qt.AlignHCenter
            spacing: 20
            Layout.topMargin: 10
            Layout.bottomMargin: 10
            CustomIcon {
                Layout.preferredWidth: 80
                Layout.preferredHeight: 80
                source: "github-symbolic.svg"
                colorize: true
                color: Appearance.colors.colOnLayer0
            }
            ColumnLayout {
                Layout.alignment: Qt.AlignVCenter
                // spacing: 10
                StyledText {
                    text: "yumesha/qs-ii"
                    font.pixelSize: Appearance.font.pixelSize.title
                }
                StyledText {
                    text: "[" + root.repositoryUrl + "](" + root.repositoryUrl + ")"
                    font.pixelSize: Appearance.font.pixelSize.normal
                    textFormat: Text.MarkdownText
                    onLinkActivated: (link) => {
                        Qt.openUrlExternally(link)
                    }
                    PointingHandLinkHover {}
                }
            }
        }

        Flow {
            Layout.fillWidth: true
            spacing: 5

            RippleButtonWithIcon {
                materialIcon: "auto_stories"
                mainText: Translation.tr("Wallpaper guide")
                onClicked: {
                    Qt.openUrlExternally(root.repositoryUrl + "/blob/master/modules/background/VIDEO-WALLPAPER.md")
                }
            }
            RippleButtonWithIcon {
                materialIcon: "adjust"
                materialIconFill: false
                mainText: Translation.tr("Issues")
                onClicked: {
                    Qt.openUrlExternally(root.repositoryUrl + "/issues")
                }
            }
            RippleButtonWithIcon {
                materialIcon: "code"
                mainText: Translation.tr("Source code")
                onClicked: {
                    Qt.openUrlExternally(root.repositoryUrl)
                }
            }
            RippleButtonWithIcon {
                materialIcon: "account_circle"
                mainText: Translation.tr("GitHub profile")
                onClicked: {
                    Qt.openUrlExternally("https://github.com/yumesha")
                }
            }

        }
        StyledText {
            Layout.fillWidth: true
            text: Translation.tr("Based on the illogical-impulse shell.")
            font.pixelSize: Appearance.font.pixelSize.small
            color: Appearance.colors.colSubtext
        }
    }
}
