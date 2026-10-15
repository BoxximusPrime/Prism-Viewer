#include "llviewerprecompiledheaders.h"
#include "llfloaterquickphoto.h"
#include "llquickphotomath.h"
#include "fsexactoit.h"

#include "llagent.h"
#include "llagentbenefits.h"
#include "llappearancemgr.h"
#include "llbutton.h"
#include "llcheckboxctrl.h"
#include "llcombobox.h"
#include "lldrawable.h"
#include "lldynamictexture.h"
#include "llfloaterperms.h"
#include "llfloatersimplesnapshot.h"
#include "llimagej2c.h"
#include "llinventoryfunctions.h"
#include "llinventorymodel.h"
#include "llinventorymodelbackgroundfetch.h"
#include "lljointstate.h"
#include "llmotion.h"
#include "llprismcollections.h"
#include "llscrolllistctrl.h"
#include "llscrolllistcolumn.h"
#include "llscrolllistitem.h"
#include "llscrolllistcell.h"
#include "llsliderctrl.h"
#include "llstatusbar.h"
#include "lltextbox.h"
#include "llviewerassetupload.h"
#include "llviewercamera.h"
#include "llviewerinventory.h"
#include "llviewerjointattachment.h"
#include "llviewershadermgr.h"
#include "llviewerwindow.h"
#include "llvoavatarself.h"
#include "pipeline.h"

namespace
{
const LLUUID PHOTO_POSE("b184bffe-95be-4dce-a927-644f5647c1ee");

// A local motion avoids asset-loading delays and takes precedence over ordinary AOs.
class LLQuickPhotoMotion final : public LLMotion
{
public:
    explicit LLQuickPhotoMotion(const LLUUID& id) : LLMotion(id) {}
    static LLMotion* create(const LLUUID& id) { return new LLQuickPhotoMotion(id); }
    bool getLoop() override { return true; }
    F32 getDuration() override { return 0.f; }
    F32 getEaseInDuration() override { return 0.2f; }
    F32 getEaseOutDuration() override { return 0.2f; }
    LLJoint::JointPriority getPriority() override { return LLJoint::ADDITIVE_PRIORITY; }
    LLMotionBlendType getBlendType() override { return NORMAL_BLEND; }
    F32 getMinPixelArea() override { return 0.f; }
    LLMotionInitStatus onInitialize(LLCharacter* character) override
    {
        struct Bone { const char* name; F32 roll; };
        // Arms 20 degrees from vertical; feet under the hips with level soles.
        const Bone bones[] = {
            {"mPelvis", 0.f}, {"mTorso", 0.f}, {"mChest", 0.f},
            {"mNeck", 0.f}, {"mHead", 0.f},
            {"mEyeLeft", 0.f}, {"mEyeRight", 0.f},
            {"mFaceEyeAltLeft", 0.f}, {"mFaceEyeAltRight", 0.f},
            {"mCollarLeft", 0.f}, {"mShoulderLeft", -70.f}, {"mElbowLeft", 0.f}, {"mWristLeft", 0.f},
            {"mCollarRight", 0.f}, {"mShoulderRight", 70.f}, {"mElbowRight", 0.f}, {"mWristRight", 0.f},
            {"mHipLeft", 3.f}, {"mKneeLeft", 0.f}, {"mAnkleLeft", -3.f}, {"mFootLeft", 0.f},
            {"mHipRight", -3.f}, {"mKneeRight", 0.f}, {"mAnkleRight", 3.f}, {"mFootRight", 0.f}
        };
        for (const Bone& bone : bones)
        {
            LLJoint* joint = character->getJoint(bone.name);
            if (!joint) return STATUS_FAILURE;
            LLPointer<LLJointState> state = new LLJointState;
            state->setJoint(joint);
            state->setUsage(LLJointState::ROT);
            state->setRotation(LLQuaternion(bone.roll * DEG_TO_RAD, LLVector3::x_axis));
            addJointState(state);
        }
        return STATUS_SUCCESS;
    }
    bool onActivate() override { return true; }
    bool onUpdate(F32, U8*) override { return true; }
    void onDeactivate() override {}
};

bool usesBakedSkin(LLViewerObject* object)
{
    for (S32 i = 0; i < object->getNumTEs(); ++i)
    {
        const LLUUID id = object->getTE(i)->getID();
        if (id == IMG_USE_BAKED_HEAD || id == IMG_USE_BAKED_UPPER || id == IMG_USE_BAKED_LOWER) return true;
    }
    for (const auto& child : object->getChildren()) if (usesBakedSkin(child)) return true;
    return false;
}
}

// Use the appearance editor's isolated render target and camera save/restore path.
class LLQuickPhotoPreview final : public LLViewerDynamicTexture
{
public:
    LLQuickPhotoPreview(S32 preset, F32 background, F32 zoom, bool mannequin,
                        const uuid_set_t& attachments, const uuid_set_t& body)
        : LLViewerDynamicTexture(256, LLQuickPhoto::frame(preset).height, 3, ORDER_MIDDLE, true),
          mPreset(preset), mBackground(background), mZoom(zoom), mMannequin(mannequin),
          mAttachments(attachments), mBody(body) {}

    bool needsRender() override
    {
        auto* pose = isAgentAvatarValid() ? gAgentAvatarp->findMotion(PHOTO_POSE) : nullptr;
        return !mRaw && mError.empty() && isAgentAvatarValid() && gAgentAvatarp->mDrawable &&
            pose && gAgentAvatarp->isMotionActive(PHOTO_POSE) && !pose->isStopped() &&
            !gAgentAvatarp->getIsAppearanceAnimating() && mWait.getElapsedTimeF32() > 1.f;
    }
    bool render() override
    {
        mCOFVersion = LLAppearanceMgr::instance().getCOFVersion();
        auto* avatar = gAgentAvatarp.get();
        auto* camera = LLViewerCamera::getInstance();
        const auto crop = LLQuickPhoto::frame(mPreset);
        const F32 height = llmax(0.5f, avatar->mBodySize.mV[VZ]);
        LLVector3 head = avatar->mHeadp->getWorldPosition();
        const F32 feet = head.mV[VZ] + height * 0.07f - height;
        LLVector3 target = avatar->mPelvisp->getWorldPosition();
        target.mV[VZ] = feet + height * (crop.bottom + crop.top) * 0.5f;
        if (mPreset == 0) { target.mV[VX] = head.mV[VX]; target.mV[VY] = head.mV[VY]; }
        const F32 fov = 0.65f;
        const F32 distance = LLQuickPhoto::distance(height, mPreset, fov, mZoom);
        LLVector3 forward(cosf(crop.yaw), sinf(crop.yaw), 0.f);
        forward = forward * avatar->mRoot->getWorldRotation();
        forward.mV[VZ] = 0.f;
        forward.normalize();

        gGL.pushUIMatrix();
        gGL.loadUIIdentity();
        gGL.matrixMode(LLRender::MM_PROJECTION);
        gGL.pushMatrix();
        gGL.matrixMode(LLRender::MM_MODELVIEW);
        gGL.pushMatrix();
        camera->setAspect(256.f / mFullHeight);
        camera->setViewNoBroadcast(fov);
        camera->setNear(0.01f);
        camera->setOriginAndLookAt(target + forward * distance, LLVector3::z_axis, target);
        camera->setPerspective(false, 0, 0, mFullWidth, mFullHeight, false);

        const S32 pixels = mFullWidth * mFullHeight;
        std::vector<F32> scene_depth, body_depth;
        mRaw = new LLImageRaw(mFullWidth, mFullHeight, 3);
        GLint pack_alignment, unpack_alignment;
        glGetIntegerv(GL_PACK_ALIGNMENT, &pack_alignment);
        glGetIntegerv(GL_UNPACK_ALIGNMENT, &unpack_alignment);
        glPixelStorei(GL_PACK_ALIGNMENT, 1);
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
        GLfloat clear_color[4];
        glGetFloatv(GL_COLOR_CLEAR_VALUE, clear_color);

        const GLenum draw_buffers[] = { GL_COLOR_ATTACHMENT0, GL_COLOR_ATTACHMENT1, GL_COLOR_ATTACHMENT2, GL_COLOR_ATTACHMENT3 };
        auto render_avatar = [&](const uuid_set_t& attachments)
        {
            LLGLDepthTest depth(GL_TRUE, GL_TRUE);
            LLGLDisable scissor(GL_SCISSOR_TEST);
            // The shared target has multiple attachments; reset the draw buffers after each impostor.
            glDrawBuffers(mBoundTarget->getNumTextures(), draw_buffers);
            glViewport(0, 0, mFullWidth, mFullHeight);
            glClearColor(mBackground, mBackground, mBackground, 1.f);
            gGL.setColorMask(true, true);
            mBoundTarget->clear();
            gPipeline.generateImpostor(avatar, true, false, nullptr, &attachments);
            gGL.flush();
            glReadBuffer(GL_COLOR_ATTACHMENT0);
        };

        if (mMannequin)
        {
            scene_depth.resize(pixels);
            body_depth.resize(pixels);
            // Only opaque body depth identifies skin in the opaque colour buffer.
            gPipeline.pushRenderTypeMask();
            gPipeline.clearRenderTypeMask(LLPipeline::RENDER_TYPE_ALPHA_PRE_WATER,
                LLPipeline::RENDER_TYPE_ALPHA_POST_WATER, LLPipeline::END_RENDER_TYPES);
            render_avatar(mBody);
            glReadPixels(0, 0, mFullWidth, mFullHeight, GL_DEPTH_COMPONENT, GL_FLOAT, body_depth.data());
            gPipeline.popRenderTypeMask();
        }
        const uuid_set_t no_grey;
        const bool success = FSExactOIT::renderPreview(*mBoundTarget, mMannequin ? mBody : no_grey,
            [&] { render_avatar(mAttachments); },
            [&]
            {
                if (!mMannequin) return;
                gGL.flush();
                LLGLSLShader::unbind();
                glReadBuffer(GL_COLOR_ATTACHMENT0);
                glReadPixels(0, 0, mFullWidth, mFullHeight, GL_RGB, GL_UNSIGNED_BYTE, mRaw->getData());
                glReadPixels(0, 0, mFullWidth, mFullHeight, GL_DEPTH_COMPONENT, GL_FLOAT, scene_depth.data());
                LLQuickPhoto::desaturate(mRaw->getData(), scene_depth.data(), body_depth.data(), pixels);
                gGL.getTexUnit(0)->bindManual(LLTexUnit::TT_TEXTURE, mBoundTarget->getTexture());
                glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, mFullWidth, mFullHeight, GL_RGB, GL_UNSIGNED_BYTE, mRaw->getData());
                gGL.getTexUnit(0)->unbind(LLTexUnit::TT_TEXTURE);
            });
        if (success)
            glReadPixels(0, 0, mFullWidth, mFullHeight, GL_RGB, GL_UNSIGNED_BYTE, mRaw->getData());
        else
        {
            mRaw = nullptr;
            mError = "Photo transparency could not be rendered. OpenGL 4.3 and enough GPU memory are required. Try refreshing.";
        }
        glPixelStorei(GL_PACK_ALIGNMENT, pack_alignment);
        glPixelStorei(GL_UNPACK_ALIGNMENT, unpack_alignment);
        glDrawBuffers(mBoundTarget->getNumTextures(), draw_buffers);
        glClearColor(clear_color[0], clear_color[1], clear_color[2], clear_color[3]);
        gGL.setColorMask(true, true);
        gGL.setSceneBlendType(LLRender::BT_ALPHA);
        gGL.matrixMode(LLRender::MM_PROJECTION);
        gGL.popMatrix();
        gGL.matrixMode(LLRender::MM_MODELVIEW);
        gGL.popMatrix();
        gGL.popUIMatrix();
        return success;
    }
    void postRender(bool success) override
    {
        // Upload the composed RGB image after transparency and mannequin processing.
        LLViewerDynamicTexture::postRender(false);
        if (success && mRaw) createGLTexture(0, mRaw);
    }
    LLPointer<LLImageRaw> raw() const { return mRaw; }
    const std::string& error() const { return mError; }
    bool currentLook() const { return mCOFVersion == LLAppearanceMgr::instance().getCOFVersion(); }
private:
    S32 mPreset;
    F32 mBackground, mZoom;
    bool mMannequin;
    uuid_set_t mAttachments, mBody;
    LLPointer<LLImageRaw> mRaw;
    LLTimer mWait;
    S32 mCOFVersion = -1;
    std::string mError;
};

LLFloaterQuickPhoto::LLFloaterQuickPhoto(const LLSD& key) : LLFloater(key) {}
LLFloaterQuickPhoto::~LLFloaterQuickPhoto() { stopPose(); }

bool LLFloaterQuickPhoto::postBuild()
{
    getChild<LLComboBox>("preset")->setCurrentByIndex(1);
    mAttachments = getChild<LLScrollListCtrl>("attachments");
    mAttachments->setCommitCallback([this](LLUICtrl*, const LLSD&) { refreshPreview(); });
    for (const char* name : {"preset", "background", "zoom"})
        getChild<LLUICtrl>(name)->setCommitCallback([this](LLUICtrl*, const LLSD&) { refreshPreview(); });
    getChild<LLUICtrl>("mannequin")->setCommitCallback([this](LLUICtrl*, const LLSD&)
        { updateMannequinControls(); refreshPreview(); });
    getChild<LLUICtrl>("isolate")->setCommitCallback([this](LLUICtrl*, const LLSD&) { isolateAttachments(); });
    getChild<LLButton>("refresh")->setClickedCallback([this](LLUICtrl*, const LLSD&) { refreshAttachments(); refreshPreview(); });
    getChild<LLButton>("wear")->setClickedCallback([this](LLUICtrl*, const LLSD&) { wearFolder(); });
    getChild<LLButton>("upload")->setClickedCallback([this](LLUICtrl*, const LLSD&) { upload(); });
    getChild<LLButton>("cancel")->setClickedCallback([this](LLUICtrl*, const LLSD&) { closeFloater(); });
    updateMannequinControls();
    return true;
}

void LLFloaterQuickPhoto::updateMannequinControls()
{
    const bool mannequin = getChild<LLCheckBoxCtrl>("mannequin")->get();
    auto* column = mAttachments->getColumn("body");
    column->setWidth(mannequin ? 42 : -1);
    if (column->mHeader) column->mHeader->setVisible(mannequin);
    mAttachments->updateColumns(true);
    for (auto* row : mAttachments->getAllData()) row->getColumn(1)->setEnabled(mannequin);
    getChild<LLView>("body_help")->setVisible(mannequin);
}

void LLFloaterQuickPhoto::onOpen(const LLSD& key)
{
    if (mUploading) return;
    mFolder = key.asUUID();
    mUploadedAsset.setNull();
    auto* folder = gInventory.getCategory(mFolder);
    if (!folder || !isAgentAvatarValid()) { closeFloater(); return; }
    mAttachments->deleteAllItems();
    getChild<LLTextBox>("folder")->setText(folder->getName());
    getChild<LLCheckBoxCtrl>("isolate")->set(LLPrismCollections::isCategory(folder->getParentUUID()));
    LLInventoryModelBackgroundFetch::instance().start(mFolder);
    if (!mOwnPose)
    {
        gAgentAvatarp->registerMotion(PHOTO_POSE, LLQuickPhotoMotion::create);
        auto* motion = gAgentAvatarp->findMotion(PHOTO_POSE);
        mOwnPose = !motion || !gAgentAvatarp->isMotionActive(PHOTO_POSE) || motion->isStopped();
        if (mOwnPose) gAgentAvatarp->LLCharacter::startMotion(PHOTO_POSE);
    }
    refreshAttachments();
    refreshPreview();
    mRefreshTimer.reset();
}

void LLFloaterQuickPhoto::stopPose()
{
    if (mOwnPose && isAgentAvatarValid()) gAgentAvatarp->LLCharacter::stopMotion(PHOTO_POSE, true);
    mOwnPose = false;
}

void LLFloaterQuickPhoto::onClose(bool)
{
    stopPose();
    mPreview = nullptr;
}

void LLFloaterQuickPhoto::status(const std::string& message)
{
    getChild<LLTextBox>("status")->setText(message);
    getChild<LLTextBox>("status")->setToolTip(message);
}

bool LLFloaterQuickPhoto::folderReady(std::string& reason)
{
    mMembers.clear();
    auto* folder = gInventory.getCategory(mFolder);
    const LLUUID trash = gInventory.findCategoryUUIDForType(LLFolderType::FT_TRASH);
    if (!folder || !gInventory.isObjectDescendentOf(mFolder, gInventory.getRootFolderID()) ||
        gInventory.isObjectDescendentOf(mFolder, trash))
    { reason = "This folder is no longer available."; return false; }
    if (!isAgentAvatarValid() || !gAgentAvatarp->isFullyLoaded())
    { reason = "Waiting for your avatar to finish loading..."; return false; }
    if (!gInventory.isCategoryComplete(mFolder))
    { reason = "Loading folder contents..."; return false; }
    LLInventoryModel::cat_array_t cats;
    LLInventoryModel::item_array_t items;
    gInventory.collectDescendents(mFolder, cats, items, LLInventoryModel::EXCLUDE_TRASH);
    for (const auto& cat : cats)
    {
        if (!gInventory.isCategoryComplete(cat->getUUID()))
        { reason = "Loading folder contents..."; return false; }
    }
    S32 missing_count = 0;
    std::string missing_names;
    for (const auto& item : items)
    {
        if (item->getIsBrokenLink())
        { reason = "This folder has a missing item. Repair its link before taking a photo."; return false; }
        if (item->getType() != LLAssetType::AT_OBJECT && item->getType() != LLAssetType::AT_CLOTHING &&
            item->getType() != LLAssetType::AT_BODYPART) continue;
        if (mMembers.insert(item->getLinkedUUID()).second && !get_is_item_worn(item->getLinkedUUID()))
        {
            ++missing_count;
            if (missing_count <= 3)
            {
                if (!missing_names.empty()) missing_names += ", ";
                missing_names += item->getName();
            }
        }
    }
    if (LLAppearanceMgr::instance().isOutfitLocked() || LLPrismCollections::busy())
    { reason = "Waiting for the outfit change to finish..."; return false; }
    const bool collection_set = LLPrismCollections::isCategory(folder->getParentUUID());
    if ((collection_set || folder->getPreferredType() == LLFolderType::FT_OUTFIT) && missing_count)
    {
        if (missing_count > 3) missing_names += llformat(" (+%d more)", missing_count - 3);
        reason = llformat("Not wearing %d %s item(s): ", missing_count, collection_set ? "set" : "outfit") +
            missing_names + ". Wear the outfit / set, then refresh.";
        return false;
    }
    if (gAgentAvatarp->isSitting())
    { reason = "Stand up for a neutral outfit photo, then refresh."; return false; }
    if (!gAgent.needsRenderAvatar() || !gAgent.needsRenderHead())
    { reason = "Leave first-person view and show your avatar, then refresh."; return false; }
    reason.clear();
    return true;
}

void LLFloaterQuickPhoto::refreshAttachments()
{
    if (mUploading || !isAgentAvatarValid()) return;
    std::map<LLUUID, std::pair<bool, bool>> previous;
    for (auto* row : mAttachments->getAllData())
        previous[row->getValue().asUUID()] = {row->getColumn(0)->getValue().asBoolean(), row->getColumn(1)->getValue().asBoolean()};
    mAttachments->deleteAllItems();
    std::string reason;
    folderReady(reason);
    const bool isolate = getChild<LLCheckBoxCtrl>("isolate")->get();
    for (const auto& point : gAgentAvatarp->mAttachmentPoints)
    {
        for (const auto& object : point.second->mAttachedObjects)
        {
            if (!object || object->isHUDAttachment()) continue;
            const LLUUID id = object->getAttachmentItemID();
            auto* item = gInventory.getItem(id);
            const auto old = previous.find(id);
            const bool body = old == previous.end() ? usesBakedSkin(object) : old->second.second;
            const bool show = isolate ? (body || mMembers.count(id)) : (old == previous.end() || old->second.first);
            LLSD row;
            row["value"] = id;
            row["columns"][0]["column"] = "show";
            row["columns"][0]["type"] = "checkbox";
            row["columns"][0]["value"] = show;
            row["columns"][1]["column"] = "body";
            row["columns"][1]["type"] = "checkbox";
            row["columns"][1]["value"] = body;
            row["columns"][2]["column"] = "name";
            row["columns"][2]["value"] = item ? item->getName() : "Loading attachment...";
            mAttachments->addElement(row);
        }
    }
    updateMannequinControls();
}

void LLFloaterQuickPhoto::isolateAttachments()
{
    std::string reason;
    folderReady(reason);
    const bool isolate = getChild<LLCheckBoxCtrl>("isolate")->get();
    for (auto* row : mAttachments->getAllData())
        row->getColumn(0)->setValue(!isolate || mMembers.count(row->getValue().asUUID()) || row->getColumn(1)->getValue().asBoolean());
    refreshPreview();
}

void LLFloaterQuickPhoto::refreshPreview()
{
    if (mUploading) return;
    mUploadedAsset.setNull();
    mPreview = nullptr;
    mCanCapture = false;
    mReadiness.clear();
    std::string reason;
    if (!folderReady(reason)) { status(reason); return; }
    uuid_set_t shown, body;
    for (auto* row : mAttachments->getAllData())
    {
        if (!row->getColumn(0)->getValue().asBoolean()) continue;
        shown.insert(row->getValue().asUUID());
        if (row->getColumn(1)->getValue().asBoolean()) body.insert(row->getValue().asUUID());
    }
    mPreview = new LLQuickPhotoPreview(getChild<LLComboBox>("preset")->getValue().asInteger(),
        static_cast<F32>(getChild<LLComboBox>("background")->getValue().asReal()), getChild<LLSliderCtrl>("zoom")->getValueF32(),
        getChild<LLCheckBoxCtrl>("mannequin")->get(), shown, body);
    status("Preparing preview...");
}

void LLFloaterQuickPhoto::wearFolder()
{
    if (mUploading) return;
    auto* folder = gInventory.getCategory(mFolder);
    if (!folder) return;
    if (LLPrismCollections::isCategory(folder->getParentUUID()))
        LLPrismCollections::wear(folder->getParentUUID(), mFolder);
    else if (folder->getPreferredType() == LLFolderType::FT_OUTFIT)
        LLAppearanceMgr::instance().replaceCurrentOutfit(mFolder);
    else
        LLAppearanceMgr::instance().addCategoryToCurrentOutfit(mFolder);
    mPreview = nullptr;
    status("Changing outfit. Refresh when your look has finished loading.");
}

void LLFloaterQuickPhoto::draw()
{
    const bool image_ready = mPreview && mPreview->raw();
    const bool retry = mUploadedAsset.notNull();
    const S32 height = mPreview ? mPreview->getFullHeight() : 256;
    const S32 cost = LLAgentBenefitsMgr::current().getTextureUploadCost(256, height);
    getChild<LLButton>("upload")->setLabel(retry ? "Retry folder picture" : llformat("Take & upload (L$%d)", cost));
    getChild<LLButton>("upload")->setEnabled(!mUploading && image_ready && (mCanCapture || retry));
    for (const char* name : {"preset", "background", "zoom", "mannequin", "isolate", "attachments", "refresh", "wear", "cancel"})
        getChild<LLUICtrl>(name)->setEnabled(!mUploading);
    if (!mUploading && !retry && mRefreshTimer.getElapsedTimeF32() > 1.f)
    {
        std::string reason;
        const bool ready = folderReady(reason);
        if (ready && !mPreview) { refreshAttachments(); refreshPreview(); }
        mCanCapture = ready && image_ready && mPreview->currentLook();
        const std::string message = !ready ? reason : mPreview && !mPreview->error().empty() ? mPreview->error() :
            !image_ready ? "Preparing neutral pose and preview..." :
            !mPreview->currentLook() ? "Your outfit changed. Refresh the preview before uploading." :
            "Ready. Refresh after textures finish loading or your look changes.";
        if (mReadiness != message) { mReadiness = message; status(message); }
        mRefreshTimer.reset();
    }
    LLFloater::draw();
    if (image_ready)
    {
        const LLRect area = getChild<LLView>("preview")->getRect();
        const F32 scale = llmin((F32)area.getWidth() / 256.f, (F32)area.getHeight() / height);
        const S32 width = ll_round(256.f * scale), draw_height = ll_round(height * scale);
        gGL.color4f(1.f, 1.f, 1.f, 1.f);
        gl_draw_scaled_image(area.mLeft + (area.getWidth() - width) / 2,
            area.mBottom + (area.getHeight() - draw_height) / 2, width, draw_height, mPreview);
    }
}

void LLFloaterQuickPhoto::upload()
{
    if (mUploading || !mPreview || !mPreview->raw()) return;
    if (mUploadedAsset.notNull()) { uploadThumbnail(); return; }
    std::string reason;
    if (!folderReady(reason)) { status(reason); return; }
    if (!mPreview->currentLook()) { status("Your outfit changed. Refresh the preview before uploading."); return; }
    const std::string cap = gAgent.getRegionCapability("NewFileAgentInventory");
    if (cap.empty() || gAgent.getRegionCapability("InventoryThumbnailUpload").empty())
    { status("Photo uploads are unavailable in this region."); return; }
    const auto raw = mPreview->raw();
    const S32 cost = LLAgentBenefitsMgr::current().getTextureUploadCost(raw->getWidth(), raw->getHeight());
    if (!can_afford_transaction(cost)) { status("Not enough L$ for this upload."); return; }
    LLPointer<LLImageJ2C> encoded = new LLImageJ2C;
    if (!encoded->encode(raw, 0.f)) { status("Could not encode this photo. Refresh and try again."); return; }
    const LLHandle<LLFloater> handle = getHandle();
    const std::string name = gInventory.getCategory(mFolder)->getName() + " - Quick Photo";
    auto upload = std::make_shared<LLNewBufferedResourceUploadInfo>(
        std::string((const char*)encoded->getData(), encoded->getDataSize()), LLUUID::null, name,
        "Outfit photo", 0, LLFolderType::FT_SNAPSHOT_CATEGORY, LLInventoryType::IT_SNAPSHOT, LLAssetType::AT_TEXTURE,
        PERM_ALL, LLFloaterPerms::getGroupPerms("Uploads"), LLFloaterPerms::getEveryonePerms("Uploads"),
        cost, LLUUID::null, false,
        [handle](LLUUID asset, LLSD response)
        {
            auto* self = dynamic_cast<LLFloaterQuickPhoto*>(handle.get());
            if (!self) return;
            self->mUploading = false;
            if (asset.isNull() || response["new_inventory_item"].asUUID().isNull())
            { self->status("Upload did not create an inventory photo. Please try again."); return; }
            self->mUploadedAsset = asset;
            self->uploadThumbnail();
        },
        [handle](LLUUID, LLSD, std::string)
        {
            if (auto* self = dynamic_cast<LLFloaterQuickPhoto*>(handle.get()))
            { self->mUploading = false; self->status("Photo upload failed. Your folder picture was not changed."); }
            return false;
        });
    mUploading = true;
    status("Uploading photo to inventory...");
    LLViewerAssetUpload::EnqueueInventoryUpload(cap, upload);
}

void LLFloaterQuickPhoto::uploadThumbnail()
{
    if (!gInventory.getCategory(mFolder) || !mPreview || !mPreview->raw())
    { status("Photo saved in Snapshots; the destination folder is no longer available."); return; }
    const auto source = mPreview->raw();
    LLPointer<LLImageRaw> thumbnail = new LLImageRaw(source->getData(), source->getWidth(), source->getHeight(), 3);
    // Folder thumbnails must be square. Letterbox tall shots rather than stretching the avatar.
    if (thumbnail->getHeight() == 512)
    {
        thumbnail->scale(128, 256);
        LLPointer<LLImageRaw> square = new LLImageRaw(256, 256, 3);
        const U8 background = static_cast<U8>(ll_round(getChild<LLComboBox>("background")->getValue().asReal() * 255.f));
        square->clear(background, background, background);
        square->setSubImage(64, 0, 128, 256, thumbnail->getData());
        thumbnail = square;
    }
    mUploading = true;
    status("Photo saved. Setting folder picture...");
    const LLHandle<LLFloater> handle = getHandle();
    LLFloaterSimpleSnapshot::uploadThumbnail(thumbnail, mFolder, LLUUID::null, [handle](const LLUUID& asset)
    {
        auto* self = dynamic_cast<LLFloaterQuickPhoto*>(handle.get());
        if (!self) return;
        self->mUploading = false;
        if (asset.isNull())
        { self->status("Photo saved in Snapshots. Retry folder picture without another paid upload."); return; }
        gInventory.notifyObservers();
        self->closeFloater();
    });
}
