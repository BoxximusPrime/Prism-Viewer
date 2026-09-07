; First is default
LoadLanguageFile "${NSISDIR}\Contrib\Language files\German.nlf"

; Language selection dialog
LangString InstallerLanguageTitle  ${LANG_GERMAN} "Installationssprache"
LangString SelectInstallerLanguage  ${LANG_GERMAN} "Bitte wÃ¤hlen Sie die Installationssprache"

; subtitle on license text caption (setup new version or update current one
LangString LicenseSubTitleUpdate ${LANG_GERMAN} " Update"
LangString LicenseSubTitleSetup ${LANG_GERMAN} " Setup"

LangString MULTIUSER_TEXT_INSTALLMODE_TITLE ${LANG_GERMAN} "Installationsmodus"
LangString MULTIUSER_TEXT_INSTALLMODE_SUBTITLE ${LANG_GERMAN} "FÃ¼r alle Benutzer (erfordert Administratorrechte) oder nur fÃ¼r den aktuellen Benutzer installieren?"
LangString MULTIUSER_INNERTEXT_INSTALLMODE_TOP ${LANG_GERMAN} "Wenn Sie dieses Installationsprogram mit Administratorrechten ausfÃ¼hren, kÃ¶nnen Sie auswÃ¤hlen, ob die Installation (beispielsweise) in c:\Programme oder unter AppData\Lokaler Ordner des aktuellen Benutzers erfolgen soll."
LangString MULTIUSER_INNERTEXT_INSTALLMODE_ALLUSERS ${LANG_GERMAN} "FÃ¼r alle Benutzer installieren"
LangString MULTIUSER_INNERTEXT_INSTALLMODE_CURRENTUSER ${LANG_GERMAN} "Nur fÃ¼r den aktuellen Benutzer installieren"

; installation directory text
LangString DirectoryChooseTitle ${LANG_GERMAN} "Installations-Ordner"
LangString DirectoryChooseUpdate ${LANG_GERMAN} "WÃ¤hlen Sie den Prism Ordner fÃ¼r dieses Update:"
LangString DirectoryChooseSetup ${LANG_GERMAN} "Pfad in dem Prism installiert werden soll:"

LangString MUI_TEXT_DIRECTORY_TITLE ${LANG_GERMAN} "Installationsverzeichnis"
LangString MUI_TEXT_DIRECTORY_SUBTITLE ${LANG_GERMAN} "WÃ¤hlen Sie das Verzeichnis aus, in dem Prism installiert werden soll:"

LangString MUI_TEXT_INSTALLING_TITLE ${LANG_GERMAN} "Prism wird installiert..."
LangString MUI_TEXT_INSTALLING_SUBTITLE ${LANG_GERMAN} "Der Prism Viewer wird im Verzeichnis $INSTDIR installiert"

LangString MUI_TEXT_FINISH_TITLE ${LANG_GERMAN} "Prism wird installiert"
LangString MUI_TEXT_FINISH_SUBTITLE ${LANG_GERMAN} "Der Prism Viewer wurde im Verzeichnis $INSTDIR installiert."

LangString MUI_TEXT_ABORT_TITLE ${LANG_GERMAN} "Installation abgebrochen"
LangString MUI_TEXT_ABORT_SUBTITLE ${LANG_GERMAN} "Der Prism Viewer wird nicht im Verzeichnis $INSTDIR installiert."

; CheckStartupParams message box
LangString CheckStartupParamsMB ${LANG_GERMAN} "Konnte Programm '$INSTNAME' nicht finden. Stilles Update fehlgeschlagen."

; installation success dialog
LangString InstSuccesssQuestion ${LANG_GERMAN} "Prism starten?"

; remove old NSIS version
LangString RemoveOldNSISVersion ${LANG_GERMAN} "ÃœberprÃ¼fe alte Version ..."

; check windows version
LangString CheckWindowsVersionDP ${LANG_GERMAN} "ÃœberprÃ¼fung der Windows Version ..."
LangString CheckWindowsVersionMB ${LANG_GERMAN} 'Prism unterstÃ¼tzt nur Windows Vista.$\n$\nDer Versuch es auf Windows $R0 zu installieren, kÃ¶nnte zu unvorhersehbaren AbstÃ¼rzen und Datenverlust fÃ¼hren.$\n$\nTrotzdem installieren?'
LangString CheckWindowsServPackMB ${LANG_GERMAN} "Wir empfehlen, das neueste Service Pack fÃ¼r Ihr Betriebssystem zu installieren, um Prism auszufÃ¼hren.$\nDies unterstÃ¼tzt die Leistung und StabilitÃ¤t des Programms."
LangString UseLatestServPackDP ${LANG_GERMAN} "Bitte verwenden Sie Windows Update, um das neueste Service Pack zu installieren."

; checkifadministrator function (install)
LangString CheckAdministratorInstDP ${LANG_GERMAN} "ÃœberprÃ¼fung der Installations-Berechtigungen ..."
LangString CheckAdministratorInstMB ${LANG_GERMAN} 'Sie besitzen ungenÃ¼gende Berechtigungen.$\nSie mÃ¼ssen ein "administrator" sein, um Prism installieren zu kÃ¶nnen.'

; checkifadministrator function (uninstall)
LangString CheckAdministratorUnInstDP ${LANG_GERMAN} "ÃœberprÃ¼fung der Entfernungs-Berechtigungen ..."
LangString CheckAdministratorUnInstMB ${LANG_GERMAN} 'Sie besitzen ungenÃ¼gende Berechtigungen.$\nSie mÃ¼ssen ein "administrator" sein, um Prism entfernen zu kÃ¶nnen..'

; checkifalreadycurrent
LangString CheckIfCurrentMB ${LANG_GERMAN} "Anscheinend ist Prism ${VERSION_LONG} bereits installiert.$\n$\nWÃ¼rden Sie es gerne erneut installieren?"

; checkcpuflags
LangString MissingSSE2 ${LANG_GERMAN} "Dieses GerÃ¤t verfÃ¼gt mÃ¶glicherweise nicht Ã¼ber eine CPU mit SSE2-UnterstÃ¼tzung, die fÃ¼r Prism ${VERSION_LONG} benÃ¶tigt wird. MÃ¶chten Sie fortfahren?"

; closesecondlife function (install)
LangString CloseSecondLifeInstDP ${LANG_GERMAN} "Warten auf die Beendigung von Prism ..."
LangString CloseSecondLifeInstMB ${LANG_GERMAN} "Prism kann nicht installiert oder ersetzt werden, wenn es bereits lÃ¤uft.$\n$\nBeenden Sie, was Sie gerade tun und klicken Sie OK, um Prism zu beenden.$\nKlicken Sie CANCEL, um die Installation abzubrechen."
LangString CloseSecondLifeInstRM ${LANG_GERMAN} "Prism failed to remove some files from a previous install."

; closesecondlife function (uninstall)
LangString CloseSecondLifeUnInstDP ${LANG_GERMAN} "Warten auf die Beendigung von Prism ..."
LangString CloseSecondLifeUnInstMB ${LANG_GERMAN} "Prism kann nicht entfernt werden, wenn es bereits lÃ¤uft.$\n$\nBeenden Sie, was Sie gerade tun und klicken Sie OK, um Prism zu beenden.$\nKlicken Sie CANCEL, um abzubrechen."

; CheckNetworkConnection
LangString CheckNetworkConnectionDP ${LANG_GERMAN} "PrÃ¼fe Netzwerkverbindung..."

; error during installation
LangString ErrorSecondLifeInstallRetry ${LANG_GERMAN} "Prism konnte nicht korrekt installiert werden, einige Dateien wurden eventuell nicht korrekt von der Installationroutine kopiert."
LangString ErrorSecondLifeInstallSupport ${LANG_GERMAN} "Bitte laden Sie den Viewer erneut von https://secondlife.com/support/downloads/ und versuchen Sie die Installation erneut. Sollte das Problem weiterhin bestehen, dann kontaktieren Sie unseren Support unter https://support.secondlife.com."

; ask to remove user's data files
LangString RemoveDataFilesMB ${LANG_GERMAN} "MÃ¶chten Sie alle anderen zu Prism gehÃ¶rigen Dateien ebenfalls ENTFERNEN?$\n$\nWir empfehlen, die Einstellungen und Cache-Dateien zu behalten, wenn Sie andere Versionen von Prism installiert haben oder eine Deinstallation durchfÃ¼hren, um Prism auf eine neuere Version zu aktualisieren."

; delete program files
LangString DeleteProgramFilesMB ${LANG_GERMAN} "Es existieren weiterhin Dateien in Ihrem Prism Programm Ordner.$\n$\nDies sind mÃ¶glicherweise Dateien, die sie modifiziert oder bewegt haben:$\n$INSTDIR$\n$\nMÃ¶chten Sie diese ebenfalls lÃ¶schen?"

; uninstall text
LangString UninstallTextMsg ${LANG_GERMAN} "Dies wird Prism ${VERSION_LONG} von Ihrem System entfernen."

; ask to remove registry keys that still might be needed by other viewers that are installed
LangString DeleteRegistryKeysMB ${LANG_GERMAN} "MÃ¶chten Sie die RegistrierungsschlÃ¼ssel der Anwendung entfernen?$\n$\nWir empfehlen, die RegistrierungsschlÃ¼ssel zu behalten, wenn Sie andere Versionen von Prism installiert haben."
