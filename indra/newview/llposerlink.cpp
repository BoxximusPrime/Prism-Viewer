/**
 * @file llposerlink.cpp
 * @brief Consent-gated, loopback-only Poser preview on the viewer main thread.
 * Copyright (C) 2026 Prism Viewer contributors.
 * SPDX-License-Identifier: LGPL-2.1-only
 */
#include "llviewerprecompiledheaders.h"
#include "llposerlink.h"
#include "llposerlinkprotocol.h"

#include "llagent.h"
#include "llagentcamera.h"
#include "llappviewer.h"
#include "lliosocket.h"
#include "llnotificationsutil.h"
#include "llposestudio.h"
#include "llstartup.h"
#include "lltimer.h"
#include "llvoavatarself.h"

namespace
{
bool available()
{
    return LLStartUp::getStartupState() == STATE_STARTED && !gDisconnected
        && !LLAppViewer::instance()->quitRequested() && isAgentAvatarValid()
        && gAgentAvatarp->isBuilt() && !gAgentAvatarp->getIsAppearanceAnimating()
        && gAgent.getTeleportState() == LLAgent::TELEPORT_NONE;
}

struct Link
{
    LLSocket::ptr_t listener, client;
    LLNotificationPtr prompt;
    std::string input, output;
    bool requested = false, accepted = false, closing = false;
    U32 poseSession = 0;
    U64 generation = 0;
    LLTimer received, retry;
    bool triedListen = false;

    bool ownsPose() const
    {
        return accepted && LLPoseStudio::instanceExists() && LLPoseStudio::instance().isActive()
            && LLPoseStudio::instance().getSession() == poseSession;
    }

    void release()
    {
        ++generation; // Cancelled/stale notifications can never approve another client.
        if (ownsPose()) LLPoseStudio::instance().end();
        accepted = false;
        if (prompt)
        {
            auto previous = prompt;
            prompt.reset();
            LLNotificationsUtil::cancel(previous);
        }
    }

    void reset()
    {
        release();
        client.reset();
        input.clear();
        output.clear();
        requested = closing = false;
    }

    void finish(const char* reply)
    {
        release();
        output += reply;
        closing = true;
        received.reset();
    }

    void flush()
    {
        if (!client) return;
        if (!output.empty())
        {
            apr_size_t size = output.size();
            const apr_status_t result = apr_socket_send(client->getSocket(), output.data(), &size);
            output.erase(0, size);
            if (result != APR_SUCCESS && !APR_STATUS_IS_EAGAIN(result)) { reset(); return; }
        }
        if (closing && output.empty()) reset();
    }

    void line(const std::string& text)
    {
        if (!requested)
        {
            std::string code;
            if (!LLPoserLinkProtocol::hello(text, code)) { finish("ERROR\n"); return; }
            if (LLPoseStudio::instance().isActive()) { finish("BUSY\n"); return; }
            requested = true;
            received.reset();
            output += "WAIT\n";
            const U64 session = generation;
            LLSD args;
            args["CODE"] = code;
            prompt = LLNotificationsUtil::add("PoserLinkRequest", args, LLSD(),
                [this, session](const LLSD& notification, const LLSD& response) {
                    if (session != generation || !client || closing) return;
                    prompt.reset();
                    if (LLNotificationsUtil::getSelectedOption(notification, response) != 0)
                    { finish("REJECT\n"); return; }
                    if (!available() || !LLPoseStudio::instance().begin(*gAgentAvatarp))
                    { finish("BUSY\n"); return; }
                    accepted = true;
                    poseSession = LLPoseStudio::instance().getSession();
                    gAgent.stopAutoPilot(true);
                    gAgent.resetControlFlags();
                    gAgent.setControlFlags(AGENT_CONTROL_STOP);
                    gAgentCamera.clearGeneralKeys();
                    output += "READY\n";
                    received.reset();
                    LLNotificationsUtil::add("PoserLinkStarted");
                });
            return;
        }
        LLPoserLinkProtocol::Rotations rotations;
        if (!ownsPose() || !LLPoserLinkProtocol::decodePose(text, rotations)
            || !LLPoseStudio::instance().applyLocalRotations(rotations))
        { finish("ERROR\n"); return; }
        received.reset();
        // One acknowledgement per frame also acts as a liveness check for Poser.
        if (output.empty()) output = "OK\n";
    }

    void update()
    {
        if (!listener && (!triedListen || retry.getElapsedTimeF32() > 5.f))
        {
            triedListen = true;
            retry.reset();
            listener = LLSocket::create(nullptr, LLSocket::STREAM_TCP, LLPoserLinkProtocol::PORT, "127.0.0.1");
        }
        if (!listener) return;

        apr_pool_t* pool = nullptr;
        if (apr_pool_create(&pool, nullptr) == APR_SUCCESS)
        {
            apr_socket_t* socket = nullptr;
            const auto result = apr_socket_accept(&socket, listener->getSocket(), pool);
            if (result == APR_SUCCESS)
            {
                auto incoming = LLSocket::create(socket, pool);
                apr_socket_opt_set(socket, APR_TCP_NODELAY, 1);
                if (client)
                {
                    apr_size_t size = 5;
                    apr_socket_send(socket, "BUSY\n", &size);
                }
                else
                {
                    reset();
                    client = incoming;
                    received.reset();
                }
            }
            else apr_pool_destroy(pool);
        }
        if (!client) return;
        if (accepted && !ownsPose()) finish("STOP\n");
        const float timeout = closing ? 1.f : (accepted ? 10.f : (requested ? 120.f : 3.f));
        if (received.getElapsedTimeF32() > timeout) { reset(); return; }
        flush();
        // Bounded reads, lines and queues keep a misbehaving local client off the render loop.
        for (int reads = 0; client && !closing && reads < 8; ++reads)
        {
            char buffer[8192];
            apr_size_t size = sizeof(buffer);
            const auto result = apr_socket_recv(client->getSocket(), buffer, &size);
            if (result != APR_SUCCESS && !APR_STATUS_IS_EAGAIN(result)) { reset(); break; }
            input.append(buffer, size);
            size_t newline;
            int lines = 0;
            while (!closing && (newline = input.find('\n')) != std::string::npos)
            {
                if (newline > LLPoserLinkProtocol::MAX_LINE || ++lines > 160)
                { finish("ERROR\n"); break; }
                const auto text = input.substr(0, newline);
                input.erase(0, newline + 1);
                line(text);
            }
            if (input.size() > LLPoserLinkProtocol::MAX_LINE || output.size() > 4096)
            { reset(); break; }
            if (APR_STATUS_IS_EAGAIN(result) || size == 0) break;
        }
        flush();
    }
};

Link& link()
{
    static Link value;
    return value;
}
}

void LLPoserLink::update()
{
    if (!available()) { shutdown(); return; }
    link().update();
}

void LLPoserLink::disconnect()
{
    auto& state = link();
    if (state.client) { state.finish("STOP\n"); state.flush(); }
}

void LLPoserLink::shutdown()
{
    auto& state = link();
    state.reset();
    state.listener.reset();
    state.triedListen = false;
}

bool LLPoserLink::isLinked()
{
    return link().ownsPose();
}
